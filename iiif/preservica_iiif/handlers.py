"""AWS Lambda entry points: webhook (API Gateway), convert (SQS) and reconcile (EventBridge schedule)."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from .settings import Settings, read_secret

logging.getLogger().setLevel(os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _sqs():
    import boto3

    return boto3.client("sqs")


def enqueue(refs: list[str], reason: str = "") -> None:
    """Up to 10 messages per SQS call; one message per entity ref."""
    url = os.environ["QUEUE_URL"]
    for i in range(0, len(refs), 10):
        entries = [{"Id": str(n), "MessageBody": json.dumps({"ref": r, "reason": reason})}
                   for n, r in enumerate(refs[i:i + 10])]
        failed = _sqs().send_message_batch(QueueUrl=url, Entries=entries).get("Failed") or []
        if failed:
            raise RuntimeError(f"couldn't queue {len(failed)} messages: {failed[0].get('Message')}")


@lru_cache(maxsize=1)
def _webhook_secret() -> str | None:
    return read_secret("WEBHOOK_SECRET_ARN", "WEBHOOK_SECRET")


@lru_cache(maxsize=1)
def _context():
    from .repository import Repository
    from .storage import S3Store

    settings = Settings.from_env()
    store = S3Store(os.environ["TILES_BUCKET"], os.environ["PUBLIC_BUCKET"], os.environ.get("DISTRIBUTION_ID") or None)
    return settings, Repository(), store


def webhook(event, context):
    from .webhook import handle

    return handle(event, _webhook_secret(), lambda refs: enqueue(refs, "webhook"))


def convert(event, context):
    """SQS batch: reports failed messages individually so the rest aren't retried."""
    from .convert import PublicPolicy, process

    settings, repo, store = _context()
    policy = PublicPolicy(repo, settings)
    failures = []
    for record in event.get("Records", []):
        try:
            ref = json.loads(record["body"])["ref"]
            result = process(ref, repo, store, settings, policy=policy, enqueue=lambda refs: enqueue(refs, "folder"))
            log.info(json.dumps({"ref": ref, "status": result.status, "detail": result.detail}))
            if result.status == "too_large":
                log.warning("%s needs the CLI on a larger machine: %s", ref, result.detail)
        except Exception:
            log.exception("failed: %s", record.get("body"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def reconcile(event, context):
    from .reconcile import reconcile as run, write_index

    settings, repo, store = _context()
    recheck_all = bool((event or {}).get("recheck_all")) or os.environ.get("RECHECK_ALL") == "true"
    summary = run(repo, store, settings, lambda refs: enqueue(refs, "reconcile"), recheck_all=recheck_all)
    write_index(store, settings)
    return summary.as_dict()
