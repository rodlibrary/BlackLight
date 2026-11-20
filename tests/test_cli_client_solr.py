import json

import pytest

from ingest import cli
from ingest.config import load_config
from ingest.preservica.client import HarvestError, NotVisible, PreservicaClient
from ingest.solr import SolrWriter
from tests.conftest import FakePreservica, FakeSolr, entity_xml, oai_page, oai_record
from tests.test_harvest import A1, A2, F1, MODS_A1, R, pages, tree

ENV = {"PRESERVICA_BASE_URL": "https://pv.example.com", "PRESERVICA_OAI_URL": "https://pv.example.com/OAI-PMH",
       "PRESERVICA_USERNAME": "svc", "PRESERVICA_PASSWORD": "pw"}


@pytest.fixture
def cfg(root, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    c = load_config(root / "config.example.yaml")
    c["state_dir"] = tmp_path / "state"
    c["preservica"]["thumbnail_dir"] = tmp_path / "thumbs"
    return c


# --------------------------------------------------------------------------- config

def test_config_defaults_and_env(cfg):
    pv = cfg["preservica"]
    assert pv["base_url"] == "https://pv.example.com"
    assert pv["metadata_prefix"] == ["MODS", "oai_dc"]
    assert cfg["solr_url"].endswith("/solr/preservica") and cfg["source"] == "preservica"


def test_config_requires_secrets(root, monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError, match="PRESERVICA_"):
        load_config(root / "config.example.yaml")


# --------------------------------------------------------------------------- Solr writer

def docs(n, run, source="preservica"):
    return [{"id": f"{source}-{i}", "source_ssi": source, "ingest_run_ssi": run} for i in range(n)]


def test_sweep_removes_records_missing_from_this_run():
    solr = FakeSolr(docs(10, "old"))
    w = SolrWriter(solr, batch_size=3)
    w.add(docs(9, "new"))
    assert w.finish("preservica", "new", sweep=True) == 1 and len(solr.docs) == 9


def test_sweep_refuses_large_deletes():
    solr = FakeSolr(docs(10, "old"))
    w = SolrWriter(solr)
    w.add(docs(2, "new"))
    with pytest.raises(RuntimeError, match="refusing to delete 8"):
        w.finish("preservica", "new", sweep=True)
    assert len(solr.docs) == 10


# --------------------------------------------------------------------------- end to end

def test_full_then_incremental_run(cfg):
    cfg["preservica"]["thumbnails"] = True
    thumbs = cfg["preservica"]["thumbnail_dir"]
    thumbs.mkdir(parents=True)
    (thumbs / "0ld00000-0000-4000-8000-000000000000.jpg").write_bytes(b"x")    # not a valid ref: left alone
    stale = "b0000000-0000-4000-8000-000000000099"
    (thumbs / f"{stale}.jpg").write_bytes(b"x")                                  # no longer indexed: pruned
    solr = FakeSolr([{"id": f"preservica-{stale}", "source_ssi": "preservica", "ingest_run_ssi": "old"}])
    client = FakePreservica(pages(), tree(), {A1: (b"jpeg", "image/jpeg")})

    first = cli.run(cfg, solr=solr, client=client, allow_large_delete=True, incremental=True)
    assert first["mode"] == "full" and first["swept"] == 1
    assert f"preservica-{A1}" in solr.docs and f"preservica-{R}" in solr.docs
    assert solr.docs[f"preservica-{A1}"]["thumbnail_file_ssi"] == f"{A1}.jpg"
    assert not (thumbs / f"{stale}.jpg").exists() and (thumbs / f"{A1}.jpg").exists()
    assert cli.read_checkpoint(cfg) is not None

    # Incremental: A2 is withdrawn; a changed A1 gets a fresh thumbnail.
    checkpoint = cli.read_checkpoint(cfg)
    p2 = {"MODS": [oai_page([oai_record(f"oai:io:{A1}", MODS_A1, tag="open")])],
          "oai_dc": [oai_page([oai_record(f"oai:io:{A2}", deleted=True)])]}
    client2 = FakePreservica(p2, tree(), {A1: (b"new", "image/jpeg")})
    second = cli.run(cfg, solr=solr, client=client2, incremental=True)
    assert second["mode"] == f"since {checkpoint}" and second["swept"] == 0
    assert client2.oai_calls[0]["from"] == checkpoint
    assert f"preservica-{A2}" not in solr.docs and f"preservica-{A1}" in solr.docs
    assert (thumbs / f"{A1}.jpg").read_bytes() == b"new"


def test_dry_run_writes_nothing(cfg, tmp_path):
    summary = cli.run(cfg, solr=None, client=FakePreservica(pages(), tree()), dry_run=True, backup_dir=tmp_path / "b")
    assert summary["indexed"] == 7 and cli.read_checkpoint(cfg) is None
    backup = json.loads(next((tmp_path / "b").glob("preservica-*.json")).read_text())
    assert {d["entity_type_ssi"] for d in backup} == {"asset", "folder"}


def test_failed_run_keeps_old_checkpoint(cfg):
    class Broken(FakePreservica):
        def oai(self, params):
            raise HarvestError("provider failed")
    with pytest.raises(HarvestError):
        cli.run(cfg, solr=FakeSolr(), client=Broken(), incremental=True)
    assert cli.read_checkpoint(cfg) is None


def test_check_command(cfg, capsys):
    from tests.conftest import OAI_HEAD, OAI_TAIL
    import xml.etree.ElementTree as ET

    class Checkable(FakePreservica):
        def oai(self, params):
            verb = params["verb"]
            if verb == "Identify":
                body = ("<Identify><repositoryName>Test Archive</repositoryName>"
                        "<deletedRecord>persistent</deletedRecord></Identify>")
            elif verb == "ListIdentifiers":
                body = (f"<ListIdentifiers><header><identifier>oai:so:{F1}</identifier></header>"
                        f"<header><identifier>oai:io:{A1}</identifier></header></ListIdentifiers>")
            else:
                body = ("<ListMetadataFormats><metadataFormat><metadataPrefix>oai_dc</metadataPrefix></metadataFormat>"
                        "</ListMetadataFormats>")
            return ET.fromstring(OAI_HEAD + body + OAI_TAIL)

    assert cli.check(cfg, client=Checkable(entities=tree())) == 0
    out = capsys.readouterr().out
    assert "Test Archive" in out and f"oai:io:{A1} carries: oai_dc" in out
    assert "['MODS']" in out and "Entity API:  ok" in out


# --------------------------------------------------------------------------- HTTP client

class Resp:
    def __init__(self, status, body=b"", payload=None, headers=None):
        self.status_code, self.content, self.text, self._p = status, body, body.decode(errors="replace"), payload
        self.headers = headers or {}

    def json(self):
        return self._p

    def iter_content(self, n):
        yield self.content

    def close(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def post(self, url, data=None, timeout=None):
        self.requests.append(("POST", url, data, None, None))
        return self.responses.pop(0)

    def get(self, url, params=None, headers=None, auth=None, timeout=None, stream=False):
        self.requests.append(("GET", url, headers, auth, params))
        return self.responses.pop(0)


SETTINGS = {"base_url": "https://pv.example.com", "oai_url": "https://pv.example.com/OAI-PMH",
            "username": "svc", "password": "pw", "tenant": "UNI"}
OK = (b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords/></OAI-PMH>')


def test_token_login_and_relogin_on_401():
    s = FakeSession([Resp(200, payload={"token": "t1"}), Resp(401), Resp(200, payload={"token": "t2"}), Resp(200, OK)])
    PreservicaClient(SETTINGS, session=s).oai({"verb": "ListRecords"})
    assert s.requests[0][:3] == ("POST", "https://pv.example.com/api/accesstoken/login",
                                 {"username": "svc", "password": "pw", "tenant": "UNI"})
    assert s.requests[1][2] == {"Preservica-Access-Token": "t1"}
    assert s.requests[3][2] == {"Preservica-Access-Token": "t2"}


def test_basic_auth_mode():
    s = FakeSession([Resp(200, OK)])
    PreservicaClient(dict(SETTINGS, auth="basic"), session=s).oai({"verb": "ListRecords"})
    assert s.requests[0][3] == ("svc", "pw")


def test_entity_and_thumbnail_requests():
    xml = b'<EntityResponse xmlns="http://preservica.com/EntityAPI/v7.0"><InformationObject/></EntityResponse>'
    s = FakeSession([Resp(200, xml), Resp(404), Resp(200, b"img", headers={"Content-Type": "image/jpeg"}), Resp(404)])
    c = PreservicaClient(dict(SETTINGS, auth="basic"), session=s)
    c.entity("io", A1)
    assert s.requests[0][1] == f"https://pv.example.com/api/entity/information-objects/{A1}"
    with pytest.raises(NotVisible):
        c.entity("so", F1)
    assert s.requests[1][1].endswith(f"/api/entity/structural-objects/{F1}")
    assert c.thumbnail("io", A1) == (b"img", "image/jpeg")
    assert s.requests[2][4] == {"id": f"sdb:IO|{A1}", "size": "medium"}
    assert c.thumbnail("so", F1) is None


def test_missing_credentials():
    with pytest.raises(HarvestError, match="PRESERVICA_USERNAME"):
        PreservicaClient(dict(SETTINGS, username=""), session=FakeSession([]))


def test_entity_xml_helper_round_trip():
    # Guard for the fixture itself: both XIP versions parse the same way.
    from ingest.preservica.hierarchy import parse_entity
    for v in ("6.0", "7.0"):
        assert parse_entity(entity_xml("so", F1, "T", parent=R, version=v), "so", F1).parent == R
