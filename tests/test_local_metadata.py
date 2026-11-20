"""Department from a DCDS_local metadata fragment, read through the Entity API."""
import xml.etree.ElementTree as ET

import pytest

from ingest.preservica.client import HarvestError, PreservicaClient
from ingest.preservica.local_metadata import validate
from tests.conftest import FakePreservica, entity_xml, oai_page, oai_record
from tests.test_cli_client_solr import SETTINGS as CLIENT_SETTINGS, FakeSession, Resp
from tests.test_harvest import A1, A2, F1, F2, MODS_A1, R, run, tree

SCHEMA = "https://library.uni.edu/schemas/dcds_local"
BASE = "https://pv.example.com/api/entity/information-objects"
URL_A1 = f"{BASE}/{A1}/metadata/frag-1"
MODS_URL = f"{BASE}/{A1}/metadata/frag-0"
CONFIG = [{"schema": SCHEMA, "fields": {"department": "department_ssim"}}]


def fragment(*departments):
    body = "".join(f"<dcds:department>{d}</dcds:department>" for d in departments)
    return ET.fromstring(f'<MetadataResponse xmlns="http://preservica.com/EntityAPI/v7.0"><MetadataContainer>'
                         f'<Content><dcds:record xmlns:dcds="{SCHEMA}">{body}</dcds:record></Content>'
                         f'</MetadataContainer></MetadataResponse>')


def client_with_fragment(frag):
    entities = tree()
    entities[("io", A1)] = entity_xml("io", A1, "a1.pdf", parent=F2, fragments=[
        ("http://www.loc.gov/mods/v3", MODS_URL), (SCHEMA + "/", URL_A1)])
    pages = {"MODS": [oai_page([oai_record(f"oai:io:{A1}", MODS_A1, tag="open")])], "oai_dc": []}
    return FakePreservica(pages, entities, fragments={URL_A1: frag} if frag is not None else {})


def test_department_indexed_from_fragment():
    client = client_with_fragment(fragment("Department of Biology", " Department of  Biology ", "Honors Program"))
    records, _, _ = run({"local_metadata": CONFIG}, client)
    doc = records[A1].to_solr("run")
    assert doc["department_ssim"] == ["Department of Biology", "Honors Program"]
    assert client.fragment_calls == [URL_A1]            # only the configured schema is fetched


def test_items_without_the_fragment_make_no_extra_requests():
    records, _, client = run({"local_metadata": CONFIG})
    assert client.fragment_calls == []
    assert "department_ssim" not in records[A2].to_solr("run")


def test_hidden_fragment_is_skipped():
    records, _, _ = run({"local_metadata": CONFIG}, client_with_fragment(None))
    assert "department_ssim" not in records[A1].to_solr("run")


def test_without_config_nothing_is_fetched():
    client = client_with_fragment(fragment("Department of Biology"))
    run({}, client)
    assert client.fragment_calls == []


def test_ignored_without_hierarchy():
    client = client_with_fragment(fragment("Department of Biology"))
    run({"local_metadata": CONFIG, "resolve_hierarchy": False}, client)
    assert client.fragment_calls == [] and client.entity_calls == []


@pytest.mark.parametrize("bad", [
    [{"fields": {"department": "department_ssim"}}],
    [{"schema": SCHEMA, "fields": {"department": "department"}}],
    [{"schema": SCHEMA, "fields": {"department": "department_ssi"}}],
])
def test_config_validation(bad):
    with pytest.raises(ValueError):
        validate(bad)


def test_client_fetches_fragments_only_from_its_own_server():
    s = FakeSession([Resp(200, b"<MetadataResponse/>")])
    c = PreservicaClient(dict(CLIENT_SETTINGS, auth="basic"), session=s)
    c.fragment(URL_A1)
    assert s.requests[0][1] == URL_A1
    for url in ("https://evil.example.com/api/entity/x", f"{BASE}/../../accesstoken", "https://pv.example.com/other"):
        with pytest.raises(HarvestError):
            c.fragment(url)


def test_folder_records_unaffected():
    records, _, _ = run({"local_metadata": CONFIG}, client_with_fragment(fragment("Biology")))
    assert records[R].entity_type == "folder" and "department_ssim" not in records[F1].to_solr("run")
