import pytest

from ingest.core import Record, RecordError, infer_media_type, safe_url
from ingest.dates import parse_date, solr_datetime, year_span


def make(**kw):
    base = dict(id="preservica-1", source="preservica", source_label="Archive", title="A title", resource_type=["text"])
    base.update(kw)
    return Record(**base)


def test_dates():
    assert solr_datetime("2019-05-01T00:00:00Z") == "2019-05-01T00:00:00Z"
    assert solr_datetime("1952-04") == "1952-04-01T00:00:00Z"
    assert solr_datetime("May 1987") == "1987-05-01T00:00:00Z"
    assert parse_date("1952-02", end=True).day == 29
    assert parse_date("1952-13-01") is None
    assert year_span("1950", "1952") == [1950, 1951, 1952]
    assert year_span(None, None, "circa 1940s-1950") == list(range(1940, 1951))
    assert year_span("1800", "2020") == []  # too wide to facet


def test_safe_url():
    assert safe_url("https://example.edu/a.pdf") == "https://example.edu/a.pdf"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("/relative/path") is None
    assert safe_url("data:text/html,hi") is None


def test_media_type():
    assert infer_media_type("PDF") == "pdf"
    assert infer_media_type(None, "https://x.edu/clip.mp4") == "video"
    assert infer_media_type("sound recording-nonmusical") == "audio"
    assert infer_media_type("MovingImage") == "video"
    assert infer_media_type("picture") == "image"
    assert infer_media_type("") is None


def test_to_solr_fields():
    doc = make(creators=["Okafor, Grace", "Okafor, Grace"], date_start="1952-04", date_end="1952-04",
               url="javascript:bad()", media_url="https://x.edu/a.jpg", media_type="image",
               ancestor_ids=["preservica-r"], ancestor_titles=["Root"], parent_id="preservica-r",
               thumbnail_file="abc-123.jpg").to_solr("run-1")
    assert doc["creator_ssim"] == ["Okafor, Grace"]          # de-duplicated
    assert doc["year_isim"] == [1952]
    assert "url_ssi" not in doc                               # unsafe URL dropped
    assert doc["media_type_ssi"] == "image"
    assert doc["entity_type_ssi"] == "asset" and doc["entity_type_ssim"] == ["Item"]
    assert doc["ancestor_titles_ssm"] == ["Root"] and doc["depth_isi"] == 1
    assert doc["has_thumbnail_bsi"] is True
    assert doc["ingest_run_ssi"] == "run-1"


def test_false_and_zero_are_kept():
    doc = make().to_solr("run")
    assert doc["has_thumbnail_bsi"] is False and doc["depth_isi"] == 0


def test_restricted_records_are_refused():
    with pytest.raises(RecordError):
        make(access_status="restricted").to_solr("run-1")


@pytest.mark.parametrize("kw", [
    {"id": "Has Spaces"}, {"title": " "}, {"resource_type": []},
    {"resource_type": ["book"]}, {"extra": {"unsuffixed": "x"}}, {"entity_type": "file"},
    {"ancestor_ids": ["a"], "ancestor_titles": []}, {"thumbnail_file": "../../etc/passwd"},
])
def test_validation(kw):
    with pytest.raises(RecordError):
        make(**kw).to_solr("run-1")
