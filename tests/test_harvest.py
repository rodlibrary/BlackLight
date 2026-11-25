"""Harvest tests against an invented Preservica: XML shaped like the documented OAI-PMH and Entity API responses.

The folder tree:

  R  University Archives (open)
  ├── F1 Flood Relief Records (open)
  │   ├── F2 Series 2: Oral histories (open)
  │   │   └── A1 oral history (MODS)
  │   ├── A2 photograph (Dublin Core only)
  │   ├── A4 open in OAI but "closed" in the Entity API
  │   └── A6 MODS says restricted (also has DC)
  └── H  Staff only (closed)
      └── F3 Public subseries (open)
          └── A3 report (Dublin Core)
  A5 deleted; A7 not visible to the service account
"""
import xml.etree.ElementTree as ET

import pytest

from ingest.core import Deletion, Record
from ingest.preservica import harvest
from ingest.preservica.client import HarvestError
from ingest.preservica.hierarchy import Hierarchy, parse_entity
from ingest.preservica.metadata import check_strip_paths, dc_document, mods_document
from ingest.preservica.oai import NS
from tests.conftest import FakePreservica, entity_xml, oai_error, oai_page, oai_record


def ref(n, kind="a"):
    return f"{kind}0000000-0000-4000-8000-{n:012d}"


R, F1, F2, F3, H = ref(1, "f"), ref(2, "f"), ref(3, "f"), ref(4, "f"), ref(5, "f")
A1, A2, A3, A4, A5, A6, A7 = (ref(i) for i in range(1, 8))

MODS_A1 = """
<mods:mods>
  <mods:titleInfo><mods:title>Oral history interview with Grace Okafor</mods:title></mods:titleInfo>
  <mods:titleInfo type="alternative"><mods:title>Okafor interview</mods:title></mods:titleInfo>
  <mods:name type="personal"><mods:namePart>Okafor, Grace</mods:namePart></mods:name>
  <mods:typeOfResource>sound recording-nonmusical</mods:typeOfResource>
  <mods:genre>oral histories</mods:genre>
  <mods:originInfo><mods:dateCreated>1987-05-03</mods:dateCreated></mods:originInfo>
  <mods:abstract>Recollections of the 1952 flood.</mods:abstract>
  <mods:subject><mods:topic>Floods</mods:topic></mods:subject>
  <mods:subject><mods:geographic>Riverton (Ohio)</mods:geographic></mods:subject>
  <mods:accessCondition type="use and reproduction"
    xlink:href="http://rightsstatements.org/vocab/InC-EDU/1.0/">In copyright, educational use.</mods:accessCondition>
  <mods:identifier type="local">uni-ms123-0003</mods:identifier>
  <mods:identifier type="aspace">aspace_8f2c1e0a91d2</mods:identifier>
  <mods:relatedItem type="host"><mods:titleInfo><mods:title>MS 123 Flood Relief</mods:title></mods:titleInfo>
    <mods:identifier>MS-123</mods:identifier></mods:relatedItem>
</mods:mods>"""

MODS_A6 = """<mods:mods><mods:titleInfo><mods:title>Medical file</mods:title></mods:titleInfo>
  <mods:accessCondition type="restriction on access">Restricted until 2040.</mods:accessCondition></mods:mods>"""


def dc(title, **fields):
    body = f"<dc:title>{title}</dc:title>" + "".join(
        f"<dc:{k}>{v}</dc:{k}>" for k, vals in fields.items() for v in (vals if isinstance(vals, list) else [vals]))
    return f'<oai_dc:dc>{body}</oai_dc:dc>'


DC_A2 = dc("Sandbagging on Main Street", creator="Daily Herald", date="1952-04-14", type=["Image", "Photographs"],
           format="image/jpeg", subject="Floods; Volunteers", rights="http://rightsstatements.org/vocab/NoC-US/1.0/",
           identifier="doi:10.1234/flood.2", description=["A crowd fills sandbags.", "Caption on verso."])
DC_A3 = dc("Annual report", type="Text", date="1960-1962", language="eng")


def tree(**overrides):
    entities = {
        ("so", R): entity_xml("so", R, "University Archives", description="Records of the university."),
        ("so", F1): entity_xml("so", F1, "Flood Relief Records", parent=R),
        ("so", F2): entity_xml("so", F2, "Series 2: Oral histories", parent=F1),
        ("so", H): entity_xml("so", H, "Staff only", tag="closed", parent=R),
        ("so", F3): entity_xml("so", F3, "Public subseries", parent=H),
        ("io", A1): entity_xml("io", A1, "a1.wav", parent=F2),
        ("io", A2): entity_xml("io", A2, "a2.tif", parent=F1, version="6.0"),
        ("io", A3): entity_xml("io", A3, "a3.pdf", parent=F3),
        ("io", A4): entity_xml("io", A4, "a4.tif", tag="closed", parent=F1),
        ("io", A6): entity_xml("io", A6, "a6.pdf", parent=F1),
    }
    entities.update(overrides)
    return entities


def pages():
    return {
        "MODS": [oai_page([oai_record(f"oai:io:{A1}", MODS_A1, tag="open"),
                           oai_record(f"oai:io:{A6}", MODS_A6)], token="t1"),
                 oai_page([oai_record(f"oai:io:{A5}", deleted=True)])],
        "oai_dc": [oai_page([oai_record(f"oai:io:{A1}", dc("Okafor (DC copy)")),
                             oai_record(f"oai:io:{A2}", DC_A2),
                             oai_record(f"oai:io:{A3}", DC_A3),
                             oai_record(f"oai:io:{A4}", dc("Closed in entity")),
                             oai_record(f"oai:io:{A7}", dc("Invisible")),
                             oai_record(f"oai:io:{A6}", dc("Medical file (DC)"))])],
    }


SETTINGS = {
    "label": "Digital Archive", "metadata_prefix": ["MODS", "oai_dc"], "public_security_tags": ["open"],
    "resolve_hierarchy": True, "include_folders": True, "skip_top_levels": 0, "collection_from": "hierarchy",
    "landing_url_template": "https://ua.example.edu/IO_{uuid}/",
    "folder_landing_url_template": "https://ua.example.edu/SO_{uuid}/",
    "media_url_template": "",
}


def run(settings=None, client=None, **kw):
    client = client or FakePreservica(pages(), tree())
    items = list(harvest(dict(SETTINGS, **(settings or {})), "preservica", client=client, **kw))
    records = {i.preservica_ref: i for i in items if isinstance(i, Record)}
    deletions = {i.ref: i for i in items if isinstance(i, Deletion)}
    return records, deletions, client


def test_assets_folders_and_removals():
    records, deletions, _ = run()
    assert set(records) == {A1, A2, A3, R, F1, F2, F3}
    assert set(deletions) == {A4, A5, A6, A7}
    assert "deleted" in deletions[A5].reason
    assert "accessCondition" in deletions[A6].reason          # MODS decided first; DC copy ignored
    assert "closed" in deletions[A4].reason                    # Entity API tag is a second gate
    assert "not visible" in deletions[A7].reason


def test_mods_record_with_breadcrumbs():
    records, _, _ = run()
    r = records[A1]
    assert r.title == "Oral history interview with Grace Okafor"    # MODS wins over the later DC copy
    assert r.metadata_format == "mods"
    assert r.ancestor_titles == ["University Archives", "Flood Relief Records", "Series 2: Oral histories"]
    assert r.ancestor_ids == [f"preservica-{R}", f"preservica-{F1}", f"preservica-{F2}"]
    assert r.parent_id == f"preservica-{F2}"
    assert r.collection == ["University Archives"]
    assert r.places == ["Riverton (Ohio)"] and r.subjects == ["Floods"]
    assert r.url == f"https://ua.example.edu/IO_{A1}/"
    doc = r.to_solr("run")
    assert doc["entity_type_ssim"] == ["Item"] and doc["depth_isi"] == 3
    assert doc["resource_type_ssim"] == ["sound recording"]
    assert doc["aspace_ref_ssi"] == "aspace_8f2c1e0a91d2"
    assert doc["year_isim"] == [1987]


def test_dublin_core_record():
    records, _, _ = run()
    r = records[A2]
    assert r.metadata_format == "oai_dc"
    assert r.resource_type == ["still image"] and r.genres == ["Photographs"]
    assert r.subjects == ["Floods", "Volunteers"]
    assert r.rights_uri == "http://rightsstatements.org/vocab/NoC-US/1.0/" and r.rights_note == []
    assert r.doi == "10.1234/flood.2"
    assert r.abstract == "A crowd fills sandbags." and r.notes == ["Caption on verso."]
    assert r.ancestor_titles == ["University Archives", "Flood Relief Records"]
    d3 = records[A3].to_solr("run")
    assert d3["year_isim"] == [1960, 1961, 1962]


def test_hidden_folders_never_appear():
    records, _, _ = run()
    assert records[A3].ancestor_titles == ["Public subseries"]     # "Staff only" and above are cut off
    for r in records.values():
        assert "Staff only" not in r.ancestor_titles
        assert r.title != "Staff only"


def test_folder_records():
    records, _, _ = run()
    root, f2 = records[R], records[F2]
    assert root.entity_type == "folder" and root.metadata_format == "entity"
    assert root.abstract == "Records of the university."
    assert root.collection == ["University Archives"]                # top-level folder is its own collection
    assert root.url == f"https://ua.example.edu/SO_{R}/"
    assert f2.ancestor_titles == ["University Archives", "Flood Relief Records"]
    assert f2.resource_type == ["mixed material"]
    assert f2.to_solr("run")["entity_type_ssim"] == ["Collection"]


def test_skip_top_levels_hides_the_root():
    records, _, _ = run({"skip_top_levels": 1})
    assert R not in records
    assert records[A1].ancestor_titles == ["Flood Relief Records", "Series 2: Oral histories"]
    assert records[A1].collection == ["Flood Relief Records"]
    assert records[F1].collection == ["Flood Relief Records"]


def test_collection_from_mods_or_both():
    records, _, _ = run({"collection_from": "mods"})
    assert records[A1].collection == ["MS 123 Flood Relief"] and records[A1].collection_id == "MS-123"
    records, _, _ = run({"collection_from": "both"})
    assert records[A1].collection == ["University Archives", "MS 123 Flood Relief"]


def test_folders_cached_one_request_each():
    _, _, client = run()
    folder_calls = [c for c in client.entity_calls if c[0] == "so"]
    assert len(folder_calls) == len(set(folder_calls))


def test_without_hierarchy():
    records, deletions, client = run({"resolve_hierarchy": False})
    assert client.entity_calls == []
    assert R not in records and A4 in records                       # no Entity API gate without it
    assert records[A1].ancestor_ids == [] and records[A1].collection == ["MS 123 Flood Relief"]


def test_oai_security_tag_gate():
    p = {"oai_dc": [oai_page([oai_record(f"oai:io:{A2}", DC_A2, tag="closed")])]}
    records, deletions, _ = run({"metadata_prefix": "oai_dc"}, FakePreservica(p, tree()))
    assert not records and A2 in deletions


def test_folder_from_oai_uses_its_metadata():
    p = {"oai_dc": [oai_page([oai_record(f"oai:so:{F1}", dc("Flood Relief Records, 1952-1960", date="1952/1960"))])]}
    records, _, _ = run({"metadata_prefix": "oai_dc"}, FakePreservica(p, tree()))
    assert records[F1].title == "Flood Relief Records, 1952-1960"
    assert records[F1].entity_type == "folder" and records[F1].ancestor_titles == ["University Archives"]


def test_thumbnails_cached_and_removed(tmp_path):
    thumbs = {A1: (b"\xff\xd8jpeg", "image/jpeg"), R: (b"\x89PNG", "image/png")}
    (tmp_path / f"{A6}.jpg").write_bytes(b"old")                    # restricted now: must go
    client = FakePreservica(pages(), tree(), thumbs)
    records, _, _ = run({"thumbnails": True, "thumbnail_dir": tmp_path}, client)
    assert records[A1].thumbnail_file == f"{A1}.jpg"
    assert (tmp_path / f"{A1}.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert records[R].thumbnail_file == f"{R}.png"
    assert records[A2].thumbnail_file is None
    assert not (tmp_path / f"{A6}.jpg").exists()
    assert all(c[0] in ("io", "so") for c in client.thumbnail_calls)
    # A second full run reuses the cached files.
    client2 = FakePreservica(pages(), tree(), thumbs)
    run({"thumbnails": True, "thumbnail_dir": tmp_path}, client2)
    assert (("io", A1, "medium") not in client2.thumbnail_calls)


def test_thumbnail_template_overrides_cache(tmp_path):
    records, _, client = run({"thumbnails": True, "thumbnail_dir": tmp_path,
                              "thumbnail_url_template": "https://img.example.edu/{uuid}.jpg"},
                             FakePreservica(pages(), tree(), {A1: (b"x", "image/jpeg")}))
    assert records[A1].thumbnail_url == f"https://img.example.edu/{A1}.jpg"
    assert records[A1].thumbnail_file is None and client.thumbnail_calls == []


def test_dry_run_writes_no_thumbnails(tmp_path):
    client = FakePreservica(pages(), tree(), {A1: (b"x", "image/jpeg")})
    run({"thumbnails": True, "thumbnail_dir": tmp_path / "t"}, client, dry_run=True)
    assert not (tmp_path / "t").exists() and client.thumbnail_calls == []


def test_resumption_and_from_parameter():
    client = FakePreservica(pages(), tree())
    list(harvest(SETTINGS, "preservica", since="2026-11-01T00:00:00Z", client=client))
    assert client.oai_calls[0] == {"verb": "ListRecords", "metadataPrefix": "MODS", "from": "2026-11-01T00:00:00Z"}
    assert client.oai_calls[1] == {"verb": "ListRecords", "resumptionToken": "t1"}


def test_oai_errors():
    client = FakePreservica({"MODS": [oai_error("cannotDisseminateFormat")]}, tree())
    with pytest.raises(HarvestError, match="cannotDisseminateFormat"):
        list(harvest(dict(SETTINGS, metadata_prefix="MODS"), "preservica", client=client))


# --------------------------------------------------------------------------- hierarchy unit tests

def test_parse_entity_any_version():
    e = parse_entity(entity_xml("io", A1, "x", parent=F2, version="6.0"), "io", A1)
    assert (e.ref, e.security_tag, e.parent) == (A1, "open", F2)


def test_hierarchy_loop_is_truncated():
    loop = {("so", F1): entity_xml("so", F1, "One", parent=F2), ("so", F2): entity_xml("so", F2, "Two", parent=F1)}
    chain = Hierarchy(FakePreservica(entities=loop), ["open"]).chain(F1)
    assert [c.title for c in chain] == ["One", "Two"][::-1]


def test_incremental_refetches_changed_assets_but_not_folders(tmp_path):
    (tmp_path / f"{A1}.jpg").write_bytes(b"old")
    (tmp_path / f"{R}.jpg").write_bytes(b"old")
    client = FakePreservica(pages(), tree(), {A1: (b"new", "image/jpeg"), R: (b"new", "image/jpeg")})
    run({"thumbnails": True, "thumbnail_dir": tmp_path}, client, since="2026-11-01T00:00:00Z")
    assert (tmp_path / f"{A1}.jpg").read_bytes() == b"new"
    assert (tmp_path / f"{R}.jpg").read_bytes() == b"old"


def test_universal_access_link_for_rod_library_portal():
    template = "https://uni.access.preservica.com/portal/en-US/asset/sdb%3AIO%7C{uuid}"
    records, _, _ = run({"landing_url_template": template, "folder_landing_url_template": ""})
    assert records[A1].url == f"https://uni.access.preservica.com/portal/en-US/asset/sdb%3AIO%7C{A1}"
    assert records[A1].to_solr("run")["url_ssi"] == records[A1].url
    assert records[R].url is None                      # no folder template yet: no button on collection pages


def test_iiif_manifest_index_limits_viewers_to_items_with_manifests(tmp_path):
    index = tmp_path / "index.json"
    index.write_text('{"manifests": ["%s"]}' % A2)
    settings = {"iiif_enabled": True,
                "iiif_manifest_url_template": "https://iiif.example.edu/manifests/{uuid}.json",
                "georeference_url_template": "https://annotations.example.edu/?url={manifest}"}
    records, _, _ = run(dict(settings, iiif_manifest_index_url=str(index)))
    assert records[A2].iiif_manifest_url == f"https://iiif.example.edu/manifests/{A2}.json"
    assert records[A2].georeference_url
    assert records[A1].iiif_manifest_url is None and records[A1].georeference_url is None
    assert records[F1].iiif_manifest_url is None

    records, _, _ = run(settings)                                  # no index: every item
    assert records[A1].iiif_manifest_url
    records, _, _ = run(dict(settings, iiif_manifest_index_url=str(tmp_path / "missing.json")))
    assert records[A2].iiif_manifest_url is None                   # unreadable index: none, not broken viewers


def test_iiif_is_off_unless_enabled(tmp_path, caplog):
    """With iiif_enabled false (the default) the templates are ignored and the index isn't read."""
    settings = {"iiif_manifest_url_template": "https://iiif.example.edu/manifests/{uuid}.json",
                "georeference_url_template": "https://annotations.example.edu/?url={manifest}",
                "iiif_manifest_index_url": str(tmp_path / "missing.json")}
    with caplog.at_level("INFO"):
        records, _, _ = run(settings)
    assert all(r.iiif_manifest_url is None and r.georeference_url is None for r in records.values())
    assert "couldn't read the IIIF manifest index" not in caplog.text
    assert "iiif_enabled is false" in caplog.text


def test_mods_download_off_by_default():
    records, _, _ = run()
    assert records[A1].mods_xml is None
    assert "mods_xml_ss" not in records[A1].to_solr("run")


def test_mods_download_stores_public_mods_only():
    records, deletions, _ = run({"mods_download": True})
    xml = records[A1].mods_xml
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<mods:mods xmlns:mods="http://www.loc.gov/mods/v3"')
    root = ET.fromstring(xml)                                   # a well-formed, standalone document
    assert root.findtext("mods:titleInfo/mods:title", namespaces=NS) == "Oral history interview with Grace Okafor"
    assert 'xlink:href="http://rightsstatements.org/vocab/InC-EDU/1.0/"' in xml
    assert records[A1].to_solr("run")["mods_xml_ss"] == xml
    assert records[A2].mods_xml is None and records[F1].mods_xml is None    # Dublin Core / folder: no MODS
    assert A6 in deletions                                      # restricted MODS never reaches the index


def test_mods_download_strip_and_foreign_markup():
    mods = ET.fromstring(
        '<mods:mods xmlns:mods="http://www.loc.gov/mods/v3" xmlns:h="http://www.w3.org/1999/xhtml">'
        '<mods:titleInfo><mods:title>T</mods:title></mods:titleInfo>'
        '<mods:note type="admin">Donor phone 555-0100</mods:note><mods:note>Public note</mods:note>'
        '<mods:extension><h:script>alert(1)</h:script></mods:extension></mods:mods>')
    xml = mods_document(mods, check_strip_paths(["mods:note[@type='admin']"]))
    assert "Donor" not in xml and "Public note" in xml
    assert "script" not in xml and "xhtml" not in xml
    assert len(mods.findall("mods:note", NS)) == 2              # the harvested element is left unchanged


def test_mods_download_size_cap_and_bad_paths():
    big = ET.fromstring('<mods:mods xmlns:mods="http://www.loc.gov/mods/v3"><mods:abstract>'
                        + "x" * (300 * 1024) + "</mods:abstract></mods:mods>")
    assert mods_document(big) is None
    with pytest.raises(ValueError):
        check_strip_paths(["mods:note[@type="])


def test_dc_download_off_by_default():
    records, _, client = run()
    assert records[A2].dc_xml is None
    assert not [c for c in client.oai_calls if c.get("verb") == "GetRecord"]


def test_dc_download_for_dublin_core_and_mods_records():
    records, deletions, client = run({"dc_download": True})
    a2 = ET.fromstring(records[A2].dc_xml)                      # harvested as Dublin Core: no extra request
    assert a2.tag == f"{{{NS['oai_dc']}}}dc"
    assert a2.findtext("dc:title", namespaces=NS) == "Sandbagging on Main Street"
    assert records[A2].to_solr("run")["dc_xml_ss"] == records[A2].dc_xml
    # A MODS record: Preservica's Dublin Core copy, fetched with GetRecord.
    a1 = ET.fromstring(records[A1].dc_xml)
    assert a1.findtext("dc:title", namespaces=NS) == "Okafor (DC copy)"
    get_records = [c for c in client.oai_calls if c.get("verb") == "GetRecord"]
    assert {c["identifier"] for c in get_records if ":io:" in c["identifier"]} == {f"oai:io:{A1}"}
    assert all(c["metadataPrefix"] == "oai_dc" for c in get_records if ":io:" in c["identifier"])
    assert A6 in deletions and records[F1].dc_xml is None       # restricted: removed; folder without OAI record: none


def test_dc_download_strip_foreign_markup_and_missing_copy():
    dc = ET.fromstring(
        '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:x="urn:x">'
        '<dc:title>T</dc:title><dc:description>Staff: check box 4</dc:description><x:private>no</x:private>'
        '</oai_dc:dc>')
    xml = dc_document(dc, check_strip_paths(["dc:description"], "dc_download_strip"))
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<oai_dc:dc ')
    assert "<dc:title>T</dc:title>" in xml and "Staff" not in xml and "private" not in xml
    # A MODS record whose Dublin Core copy the provider doesn't have still gets its MODS.
    client = FakePreservica({"MODS": pages()["MODS"]}, tree())
    records, _, _ = run({"dc_download": True, "mods_download": True}, client=client)
    assert records[A1].dc_xml is None and records[A1].mods_xml


FOLDER_MODS = ('<mods:mods><mods:titleInfo><mods:title>University Archives</mods:title></mods:titleInfo>'
               '<mods:abstract>Records of the university.</mods:abstract></mods:mods>')


def test_folder_downloads_fetched_with_public_checks():
    folder_records = {
        "MODS": [oai_record(f"oai:so:{R}", FOLDER_MODS, tag="open"),
                 oai_record(f"oai:so:{F2}", MODS_A6.replace("Medical file", "Series 2"))],   # restricts access
        "oai_dc": [oai_record(f"oai:so:{R}", dc("University Archives")),
                   oai_record(f"oai:so:{F1}", dc("Flood Relief Records"), tag="closed"),
                   oai_record(f"oai:so:{F2}", dc("Series 2"))],
    }
    client = FakePreservica(pages(), tree(), get_records=folder_records)
    records, _, _ = run({"mods_download": True, "dc_download": True}, client=client)
    root = records[R]
    assert ET.fromstring(root.mods_xml).findtext("mods:titleInfo/mods:title", namespaces=NS) == "University Archives"
    assert ET.fromstring(root.dc_xml).findtext("dc:title", namespaces=NS) == "University Archives"
    assert records[F1].dc_xml is None                           # its OAI record carries a closed tag
    assert records[F2].mods_xml is None and records[F2].dc_xml is None   # MODS restricts: neither offered
    assert records[F3].mods_xml is None and records[F3].dc_xml is None   # no OAI record at all
    assert root.metadata_format == "entity" and root.title == "University Archives"


def test_folder_downloads_cost_nothing_when_off():
    client = FakePreservica(pages(), tree(), get_records={"oai_dc": [oai_record(f"oai:so:{R}", dc("U"))]})
    run(client=client)
    assert not [c for c in client.oai_calls if c.get("verb") == "GetRecord"]
