"""HTTP access to Preservica: token login, OAI-PMH, the Entity API and the Content API.

Endpoints used (developers.preservica.com):
  POST {base_url}/api/accesstoken/login                      form: username, password[, tenant]
  GET  {oai_url}?verb=...                                     OAI-PMH data provider
  GET  {base_url}/api/entity/information-objects/{ref}        asset: title, security tag, parent
  GET  {base_url}/api/entity/structural-objects/{ref}         folder: title, description, security tag, parent
  GET  {base_url}/api/entity/information-objects/{ref}/metadata/{id}   one metadata fragment
  GET  {base_url}/api/content/thumbnail?id=sdb:IO|{ref}&size=medium

Every call runs as the configured service account, so results never include
more than that account's role can see. Use a read-only account whose role sees
only the security tags you publish.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

ENTITY_PATHS = {"io": "information-objects", "so": "structural-objects"}
SDB_TYPES = {"io": "IO", "so": "SO"}
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024


class HarvestError(RuntimeError):
    """Preservica failed part-way; the run must not sweep or advance its checkpoint."""


class NotVisible(Exception):
    """The entity doesn't exist or the service account may not see it (403/404)."""


class PreservicaClient:
    def __init__(self, settings: dict, session: requests.Session | None = None):
        self.s = settings
        self.session = session or self._session()
        self.mode = settings.get("auth", "token")
        self.base_url = (settings.get("base_url") or "").rstrip("/")
        self.delay = float(settings.get("request_delay") or 0)
        self.token: str | None = None
        if not settings.get("username") or not settings.get("password"):
            raise HarvestError("set PRESERVICA_USERNAME and PRESERVICA_PASSWORD")
        if not settings.get("oai_url"):
            raise HarvestError("set PRESERVICA_OAI_URL")
        if self.mode == "token" and not self.base_url:
            raise HarvestError("set PRESERVICA_BASE_URL (needed for the token login)")

    @staticmethod
    def _session() -> requests.Session:
        s = requests.Session()
        retry = Retry(total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "POST"), respect_retry_after_header=True)
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = "PreservicaBlacklight-ingest/0.1"
        return s

    # ------------------------------------------------------------------ auth

    def login(self) -> None:
        data = {"username": self.s["username"], "password": self.s["password"]}
        if self.s.get("tenant"):
            data["tenant"] = self.s["tenant"]
        resp = self.session.post(f"{self.base_url}/api/accesstoken/login", data=data, timeout=60)
        if resp.status_code != 200:
            raise HarvestError(f"Preservica login failed ({resp.status_code})")
        token = resp.json().get("token")
        if not token:
            raise HarvestError("Preservica login returned no token")
        self.token = token

    def _request(self, url: str, params: dict | None = None, *, timeout: int = 300,
                 stream: bool = False) -> requests.Response:
        """GET with auth, logging in again once if the token has expired."""
        for attempt in (1, 2):
            kwargs = {"params": params, "timeout": timeout, "stream": stream}
            if self.mode == "basic":
                kwargs["auth"] = (self.s["username"], self.s["password"])
            else:
                if not self.token:
                    self.login()
                kwargs["headers"] = {"Preservica-Access-Token": self.token}
            if self.delay:
                time.sleep(self.delay)
            resp = self.session.get(url, **kwargs)
            if resp.status_code == 401 and self.mode != "basic" and attempt == 1:
                self.token = None  # tokens expire after a short time; log in again once
                continue
            return resp
        raise HarvestError(f"{url}: unauthorized after re-login")

    # ------------------------------------------------------------------ OAI-PMH

    def oai(self, params: dict) -> ET.Element:
        resp = self._request(self.s["oai_url"], params)
        if resp.status_code != 200:
            raise HarvestError(f"OAI-PMH returned {resp.status_code}: {resp.text[:200]}")
        return ET.fromstring(resp.content)

    # ------------------------------------------------------------------ Entity API

    def entity(self, kind: str, ref: str) -> ET.Element:
        """The EntityResponse XML for an asset ('io') or folder ('so'). Raises NotVisible on 403/404."""
        url = f"{self.base_url}/api/entity/{ENTITY_PATHS[kind]}/{ref}"
        resp = self._request(url, timeout=120)
        if resp.status_code in (403, 404):
            raise NotVisible(f"{kind}:{ref}")
        if resp.status_code != 200:
            raise HarvestError(f"Entity API returned {resp.status_code} for {kind}:{ref}")
        return ET.fromstring(resp.content)

    def fragment(self, url: str) -> ET.Element:
        """A metadata fragment linked from an EntityResponse. Only URLs under this server's Entity API are
        fetched, so the access token is never sent anywhere else."""
        prefix = f"{self.base_url}/api/entity/"
        if not self.base_url or not url.startswith(prefix) or ".." in url:
            raise HarvestError(f"refusing to fetch metadata fragment outside {prefix}: {url}")
        resp = self._request(url, timeout=120)
        if resp.status_code in (403, 404):
            raise NotVisible(url)
        if resp.status_code != 200:
            raise HarvestError(f"Entity API returned {resp.status_code} for {url}")
        return ET.fromstring(resp.content)

    # ------------------------------------------------------------------ Content API

    def thumbnail(self, kind: str, ref: str, size: str = "medium") -> tuple[bytes, str] | None:
        """(image bytes, content type), or None if Preservica has no thumbnail for the entity."""
        url = f"{self.base_url}/api/content/thumbnail"
        resp = self._request(url, {"id": f"sdb:{SDB_TYPES[kind]}|{ref}", "size": size}, timeout=120, stream=True)
        try:
            if resp.status_code in (204, 403, 404):
                return None
            if resp.status_code != 200:
                log.warning("thumbnail for %s:%s returned %s", kind, ref, resp.status_code)
                return None
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            body = b""
            for chunk in resp.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_THUMBNAIL_BYTES:
                    log.warning("thumbnail for %s:%s is larger than %d bytes; skipped", kind, ref, MAX_THUMBNAIL_BYTES)
                    return None
            return body, ctype
        finally:
            resp.close()
