"""Receive Preservica webhook calls (through API Gateway) and queue the entities they name.

Preservica's handshake and signature, as documented for pyPreservica:
  - subscribing: a POST with a `challengeCode` query parameter; reply with that code and its
    hex HMAC-SHA256, keyed with the shared secret
  - each notification: a `Preservica-Signature` header holding the hex HMAC-SHA256 of
    "preservica-webhook-auth" + the raw body, and a JSON body {"events": [{"entityRef": ...}, ...]}
Anything without a valid signature is refused, so only Preservica can queue work.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Callable

log = logging.getLogger(__name__)

PREFIX = "preservica-webhook-auth"


def sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _header(event: dict, name: str) -> str | None:
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _body(event: dict) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return body


def entity_refs(payload: dict) -> list[str]:
    seen, out = set(), []
    for e in payload.get("events") or []:
        ref = e.get("entityRef") if isinstance(e, dict) else None
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def handle(event: dict, secret: str, enqueue: Callable[[list[str]], None]) -> dict:
    if not secret:
        log.error("no webhook secret configured")
        return _response(500, {"error": "not configured"})

    challenge = (event.get("queryStringParameters") or {}).get("challengeCode")
    if challenge:
        return _response(200, {"challengeCode": challenge, "challengeResponse": sign(secret, challenge)})

    body = _body(event)
    given = _header(event, "Preservica-Signature") or ""
    if not hmac.compare_digest(sign(secret, PREFIX + body), given):
        log.warning("refused a webhook call with a bad signature")
        return _response(401, {"error": "bad signature"})
    try:
        refs = entity_refs(json.loads(body))
    except ValueError:
        return _response(400, {"error": "body isn't JSON"})
    if refs:
        enqueue(refs)
    log.info("queued %d entities", len(refs))
    return _response(200, {"queued": len(refs)})
