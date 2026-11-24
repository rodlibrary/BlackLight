import base64
import json

from preservica_iiif.webhook import PREFIX, handle, sign

SECRET = "shh"


def call(body, signature=None, headers_case="Preservica-Signature", b64=False):
    raw = json.dumps(body)
    sig = signature if signature is not None else sign(SECRET, PREFIX + raw)
    queued = []
    event = {"headers": {headers_case: sig},
             "body": base64.b64encode(raw.encode()).decode() if b64 else raw, "isBase64Encoded": b64}
    return handle(event, SECRET, queued.extend), queued


def test_challenge():
    r = handle({"queryStringParameters": {"challengeCode": "abc123"}}, SECRET, lambda refs: None)
    assert json.loads(r["body"]) == {"challengeCode": "abc123", "challengeResponse": sign(SECRET, "abc123")}


def test_signed_events_are_queued_once_each():
    body = {"events": [{"entityRef": "a"}, {"entityRef": "b"}, {"entityRef": "a"}, {"other": 1}]}
    r, queued = call(body)
    assert r["statusCode"] == 200 and queued == ["a", "b"]


def test_lowercase_header_and_base64_body():                # API Gateway HTTP APIs lower-case headers
    r, queued = call({"events": [{"entityRef": "a"}]}, headers_case="preservica-signature", b64=True)
    assert r["statusCode"] == 200 and queued == ["a"]


def test_bad_or_missing_signature_is_refused():
    for sig in ("nope", ""):
        r, queued = call({"events": [{"entityRef": "a"}]}, signature=sig)
        assert r["statusCode"] == 401 and queued == []


def test_no_secret_configured():
    assert handle({"body": "{}"}, "", lambda refs: None)["statusCode"] == 500
