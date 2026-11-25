"""Map coordinates: parsing, mapping from MODS / Dublin Core / DCDS_local, and Solr fields."""
import xml.etree.ElementTree as ET

import pytest

from ingest.core import Record, RecordError
from ingest.geo import parse_point, parse_points
from ingest.preservica.metadata import dc_fields, mods_fields
from tests.conftest import FakePreservica, entity_xml, oai_page, oai_record
from tests.test_harvest import A1, A2, F2, run, tree


@pytest.mark.parametrize("text, expected", [
    ("42.5139, -92.4632", (42.5139, -92.4632)),
    ("42.5139 -92.4632", (42.5139, -92.4632)),
    ("42.5139N, 92.4632W", (42.5139, -92.4632)),
    ("N 42.5 W 92.5", (42.5, -92.5)),
    ("42.5 S, 92.5 E", (-42.5, 92.5)),
    ("lat: 42.5, long: -92.4", (42.5, -92.4)),
    ("POINT(-92.4632 42.5139)", (42.5139, -92.4632)),
    ("ENVELOPE(-93, -92, 43, 42)", (42.5, -92.5)),
    ("-93, -92, 43, 42", (42.5, -92.5)),        # MODS decimal bbox W, E, N, S
])
def test_parse_point(text, expected):
    assert parse_point(text) == expected


@pytest.mark.parametrize("text", ["Cedar Falls (Iowa)", "", None, "95.0, 10.0", "42.5, 190",
                                  "W 92°30'--W 92°20'/N 42°35'--N 42°30'"])
def test_unparseable_or_out_of_range(text):
    assert parse_point(text) is None


def test_parse_points_dedupes():
    assert parse_points(["42.5, -92.4", "42.5 -92.4", "nowhere"]) == [(42.5, -92.4)]


NS = 'xmlns:mods="http://www.loc.gov/mods/v3" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" ' \
     'xmlns:dc="http://purl.org/dc/elements/1.1/"'


def test_mods_cartographics_coordinates():
    mods = ET.fromstring(f'<mods:mods {NS}><mods:titleInfo><mods:title>T</mods:title></mods:titleInfo>'
                         '<mods:subject><mods:cartographics><mods:coordinates>42.5139, -92.4632</mods:coordinates>'
                         '</mods:cartographics></mods:subject></mods:mods>')
    assert mods_fields(mods)["coordinates"] == [(42.5139, -92.4632)]


def test_dc_coverage_point_is_coordinates_not_place():
    dc = ET.fromstring(f'<oai_dc:dc {NS}><dc:title>T</dc:title><dc:coverage>Cedar Falls (Iowa)</dc:coverage>'
                       '<dc:coverage>42.5139; -92.4632</dc:coverage></oai_dc:dc>')
    f = dc_fields(dc)
    assert f["coordinates"] == [(42.5139, -92.4632)]
    assert f["places"] == ["Cedar Falls (Iowa)"]


def make(**kw):
    return Record(id="preservica-1", source="preservica", source_label="A", title="T", resource_type=["still image"], **kw)


def test_solr_fields():
    doc = make(coordinates=[(42.5139, -92.4632)], georeference_url="https://annotations.example.org/maps/1").to_solr("r")
    assert doc["coordinates_srpt"] == ["42.5139,-92.4632"] and doc["coordinates_ssm"] == ["42.5139,-92.4632"]
    assert doc["has_coordinates_bsi"] is True and doc["georeference_url_ssi"].startswith("https://")
    assert make().to_solr("r")["has_coordinates_bsi"] is False


def test_out_of_range_rejected():
    with pytest.raises(RecordError):
        make(coordinates=[(95.0, 10.0)]).to_solr("r")


def test_harvest_dc_coordinates_and_georeference_template():
    dc = (f'<oai_dc:dc {NS}><dc:title>Bird\'s-eye view of Cedar Falls</dc:title><dc:type>Image</dc:type>'
          '<dc:coverage>42.5277, -92.4453</dc:coverage></oai_dc:dc>')
    pages = {"oai_dc": [oai_page([oai_record(f"oai:io:{A2}", dc)])]}
    records, _, _ = run({"metadata_prefix": "oai_dc",
                         "iiif_enabled": True,
                         "iiif_manifest_url_template": "https://iiif.example.edu/{uuid}/manifest",
                         "georeference_url_template": "https://annotations.example.org/?url={manifest}"},
                        FakePreservica(pages, tree()))
    r = records[A2]
    assert r.coordinates == [(42.5277, -92.4453)]
    assert r.georeference_url == f"https://annotations.example.org/?url=https%3A%2F%2Fiiif.example.edu%2F{A2}%2Fmanifest"


def test_no_georeference_without_manifest():
    pages = {"oai_dc": [oai_page([oai_record(f"oai:io:{A2}", f'<oai_dc:dc {NS}><dc:title>T</dc:title></oai_dc:dc>')])]}
    records, _, _ = run({"metadata_prefix": "oai_dc", "georeference_url_template": "https://x.org/?url={manifest}"},
                        FakePreservica(pages, tree()))
    assert records[A2].georeference_url is None


def test_coordinates_from_dcds_local():
    schema = "https://library.uni.edu/schemas/dcds_local"
    url = f"https://pv.example.com/api/entity/information-objects/{A1}/metadata/frag-1"
    entities = tree()
    entities[("io", A1)] = entity_xml("io", A1, "a1.tif", parent=F2, fragments=[(schema, url)])
    frag = ET.fromstring(f'<MetadataResponse><Content><d:record xmlns:d="{schema}"><d:geo>42.51, -92.46</d:geo>'
                         f'<d:department>Geography</d:department></d:record></Content></MetadataResponse>')
    pages = {"oai_dc": [oai_page([oai_record(f"oai:io:{A1}", f'<oai_dc:dc {NS}><dc:title>T</dc:title></oai_dc:dc>')])]}
    config = [{"schema": schema, "fields": {"geo": "coordinates", "department": "department_ssim"}}]
    records, _, _ = run({"metadata_prefix": "oai_dc", "local_metadata": config},
                        FakePreservica(pages, entities, fragments={url: frag}))
    doc = records[A1].to_solr("r")
    assert doc["coordinates_srpt"] == ["42.51,-92.46"] and doc["department_ssim"] == ["Geography"]
    assert "coordinates" not in doc
