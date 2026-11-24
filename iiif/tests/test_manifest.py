from preservica_iiif.manifest import NAVPLACE_CONTEXT, build_manifest
from preservica_iiif.settings import Settings

PAGES = [{"image_id": "abc_0001", "width": 2000, "height": 1500, "label": "Front"},
         {"image_id": "abc_0002", "width": 2000, "height": 1500, "label": "Back"}]


def test_manifest_shape(settings):
    fields = {"title": "Sandbagging, 2008", "abstract": "Volunteers on Main Street.", "date_display": "2008",
              "subjects": ["Floods"], "rights_uri": "https://rightsstatements.org/vocab/InC-EDU/1.0/"}
    m = build_manifest(settings, "abc", fields, "fallback", PAGES, "https://portal.example.edu/asset/abc")
    assert m["id"] == "https://iiif.example.edu/manifests/abc.json"
    assert m["label"] == {"none": ["Sandbagging, 2008"]}
    assert m["rights"] == "http://rightsstatements.org/vocab/InC-EDU/1.0/"
    assert [c["label"]["none"][0] for c in m["items"]] == ["Front", "Back"]
    body = m["items"][0]["items"][0]["items"][0]["body"]
    assert body["service"][0] == {"id": "https://iiif.example.edu/iiif/3/abc_0001", "type": "ImageService3",
                                  "profile": "level2"}
    assert m["items"][0]["items"][0]["items"][0]["target"] == m["items"][0]["id"]
    assert m["homepage"][0]["id"].endswith("/asset/abc")
    assert m["thumbnail"][0]["id"].endswith("/abc_0001/full/!400,400/0/default.jpg")
    assert "navPlace" not in m and isinstance(m["@context"], str)


def test_navplace_is_longitude_first(settings):
    m = build_manifest(settings, "abc", {"coordinates": [(42.5355, -92.4453)]}, "T", PAGES[:1])
    assert m["@context"][0] == NAVPLACE_CONTEXT
    assert m["navPlace"]["features"][0]["geometry"]["coordinates"] == [-92.4453, 42.5355]


def test_other_rights_text_goes_in_metadata(settings):
    m = build_manifest(settings, "abc", {"rights_uri": "https://library.uni.edu/rights",
                                         "rights_note": ["Ask the archivist."]}, "T", PAGES[:1])
    assert "rights" not in m
    assert {"label": {"en": ["Rights"]}, "value": {"none": ["Ask the archivist."]}} in m["metadata"]


def test_image_api_2():
    s = Settings(public_base_url="https://iiif.example.edu", image_api_base="https://iiif.example.edu/iiif/2")
    m = build_manifest(s, "abc", {}, "T", PAGES[:1])
    svc = m["items"][0]["items"][0]["items"][0]["body"]["service"][0]
    assert svc["@type"] == "ImageService2" and svc["@id"].endswith("/iiif/2/abc_0001")
