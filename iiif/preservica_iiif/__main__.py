"""Command line, for trying the pipeline locally, converting files too large for Lambda,
and subscribing the webhook.

  python -m preservica_iiif convert REF [REF ...] [--force] [--no-size-limit] [--local DIR]
  python -m preservica_iiif withdraw REF [--local DIR]
  python -m preservica_iiif reconcile [--all] [--dry-run] [--allow-large-withdrawal] [--local DIR]
  python -m preservica_iiif subscribe URL --trigger INDEXED|SECURITY_CHANGED|MOVED

Settings come from the same environment variables as the Lambda functions (see the README).
With --local, tiles and manifests are written to a folder instead of S3, and queued refs are
converted straight away.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .settings import Settings


def _store(args):
    if args.local:
        from .storage import LocalStore

        return LocalStore(args.local)
    from .storage import S3Store

    return S3Store(os.environ["TILES_BUCKET"], os.environ["PUBLIC_BUCKET"], os.environ.get("DISTRIBUTION_ID") or None)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m preservica_iiif")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("convert", "withdraw", "reconcile"):
        sp = sub.add_parser(name)
        sp.add_argument("--local", metavar="DIR", help="write to this folder instead of S3")
        if name in ("convert", "withdraw"):
            sp.add_argument("refs", nargs="+")
        if name == "convert":
            sp.add_argument("--force", action="store_true", help="rebuild even if unchanged")
            sp.add_argument("--no-size-limit", action="store_true", help="for files too large for Lambda")
        if name == "reconcile":
            sp.add_argument("--all", action="store_true", help="re-check every public asset")
            sp.add_argument("--dry-run", action="store_true")
            sp.add_argument("--allow-large-withdrawal", action="store_true")
    sp = sub.add_parser("subscribe")
    sp.add_argument("url")
    sp.add_argument("--trigger", default="INDEXED", choices=["INDEXED", "SECURITY_CHANGED", "MOVED"])
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "subscribe":
        from pyPreservica import TriggerType, WebHooksAPI

        from .settings import read_secret

        secret = read_secret("WEBHOOK_SECRET_ARN", "WEBHOOK_SECRET")
        if not secret:
            p.error("set WEBHOOK_SECRET (or WEBHOOK_SECRET_ARN) first")
        print(WebHooksAPI().subscribe(args.url, TriggerType[args.trigger], secret))
        return 0

    from .convert import PublicPolicy, process, withdraw
    from .repository import Repository

    settings, store = Settings.from_env(), _store(args)
    if args.cmd == "withdraw":
        for ref in args.refs:
            print(json.dumps(withdraw(ref, store, settings, "withdrawn by hand").__dict__))
        return 0

    repo = Repository()
    policy = PublicPolicy(repo, settings)
    if args.cmd == "convert":
        if args.no_size_limit:
            settings.max_source_bytes = 0
        queue = list(args.refs)
        while queue:
            r = process(queue.pop(0), repo, store, settings, policy=policy, force=args.force, enqueue=queue.extend)
            print(json.dumps({"ref": r.ref, "status": r.status, "detail": r.detail}))
        return 0

    from .reconcile import reconcile, write_index

    queued: list[str] = []
    summary = reconcile(repo, store, settings, queued.extend, recheck_all=args.all, dry_run=args.dry_run,
                        allow_large_withdrawal=args.allow_large_withdrawal)
    if not args.dry_run:
        if args.local:
            for ref in queued:
                process(ref, repo, store, settings, policy=policy, enqueue=queued.extend)
        else:
            from .handlers import enqueue

            for i in range(0, len(queued), 100):
                enqueue(queued[i:i + 100], "reconcile")
        write_index(store, settings)
    print(json.dumps(summary.as_dict()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
