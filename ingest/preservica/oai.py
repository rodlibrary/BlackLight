"""OAI-PMH requests against Preservica's data provider.

How Preservica's provider behaves (developers.preservica.com, OAI-PMH Data Provider):
  - authentication is required; results reflect the service account's permissions
  - identifiers look like oai:io:<uuid> (assets) and oai:so:<uuid> (folders)
  - a schema such as MODS is returned only for records with that metadata embedded;
    oai_dc is available for every record
  - deletions are kept indefinitely as <header status="deleted">
  - 200 records per response, continued with resumptionToken
  - from/until use YYYY-MM-DDThh:mm:ssZ
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterator

from .client import HarvestError, PreservicaClient

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "mods": "http://www.loc.gov/mods/v3",
    "xlink": "http://www.w3.org/1999/xlink",
}
OAI_ID = re.compile(r"^oai:(io|so):([0-9A-Za-z-]+)$")


def _check(root: ET.Element, allow_empty: bool = False) -> bool:
    """Raise on an OAI error; return False for noRecordsMatch when allowed."""
    err = root.find("oai:error", NS)
    if err is None:
        return True
    if allow_empty and err.get("code") == "noRecordsMatch":
        return False
    raise HarvestError(f"OAI-PMH error {err.get('code')}: {(err.text or '').strip()}")


def list_records(client: PreservicaClient, prefix: str, since: str | None = None,
                 set_spec: str | None = None) -> Iterator[ET.Element]:
    """Yield every <record>, following resumption tokens. Raises HarvestError on OAI errors."""
    params = {"verb": "ListRecords", "metadataPrefix": prefix}
    if since:
        params["from"] = since
    if set_spec:
        params["set"] = set_spec
    while True:
        root = client.oai(params)
        if not _check(root, allow_empty=True):
            return
        lr = root.find("oai:ListRecords", NS)
        if lr is None:
            raise HarvestError("OAI-PMH response has no ListRecords element")
        yield from lr.findall("oai:record", NS)
        token_el = lr.find("oai:resumptionToken", NS)
        token = (token_el.text or "").strip() if token_el is not None else ""
        if not token:
            return
        params = {"verb": "ListRecords", "resumptionToken": token}


def identify(client: PreservicaClient) -> dict:
    root = client.oai({"verb": "Identify"})
    _check(root)
    ident = root.find("oai:Identify", NS)
    if ident is None:
        raise HarvestError("OAI-PMH Identify response has no Identify element")
    return {_local(c.tag): (c.text or "").strip() for c in ident if (c.text or "").strip()}


def list_metadata_formats(client: PreservicaClient, identifier: str | None = None) -> list[dict]:
    params = {"verb": "ListMetadataFormats"}
    if identifier:
        params["identifier"] = identifier
    root = client.oai(params)
    _check(root)
    return [{"prefix": (f.findtext("oai:metadataPrefix", "", NS) or "").strip(),
             "namespace": (f.findtext("oai:metadataNamespace", "", NS) or "").strip()}
            for f in root.findall("oai:ListMetadataFormats/oai:metadataFormat", NS)]


def first_identifier(client: PreservicaClient, prefix: str = "oai_dc") -> str | None:
    """One asset identifier, for checking which schemas are embedded."""
    root = client.oai({"verb": "ListIdentifiers", "metadataPrefix": prefix})
    if not _check(root, allow_empty=True):
        return None
    for h in root.findall("oai:ListIdentifiers/oai:header", NS):
        ident = (h.findtext("oai:identifier", "", NS) or "").strip()
        if ident.startswith("oai:io:") and h.get("status") != "deleted":
            return ident
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
