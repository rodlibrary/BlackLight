"""Command line: python -m ingest [--config FILE] {check,run} ..."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from .config import load_config
from .core import Deletion, RecordError
from .solr import SolrWriter

log = logging.getLogger("ingest")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _state_file(cfg: dict) -> Path:
    return cfg["state_dir"] / f"{cfg['source']}.json"


def read_checkpoint(cfg: dict) -> str | None:
    path = _state_file(cfg)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("last_success")


def write_checkpoint(cfg: dict, started: dt.datetime) -> None:
    path = _state_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The harvest's start time, so changes made while it ran are picked up next time.
    path.write_text(json.dumps({"last_success": started.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")


def rejected_too_many(rejected: int, added: int) -> bool:
    """If more than 5% of records failed validation, skip the sweep rather than delete their old copies."""
    total = rejected + added
    if total and rejected / total > 0.05:
        log.warning("%d of %d records rejected; skipping stale-record removal this run", rejected, total)
        return True
    return False


def run(cfg: dict, *, dry_run: bool = False, backup_dir: Path | None = None, allow_large_delete: bool = False,
        sweep: bool = True, incremental: bool = False, refresh_thumbnails: bool = False,
        solr=None, client=None) -> dict:
    from .preservica import harvest

    settings = cfg["preservica"]
    source = cfg["source"]
    started = _now()
    run_id = f"{source}-{started.strftime('%Y%m%dT%H%M%SZ')}"

    since = read_checkpoint(cfg) if incremental else None
    if incremental and since is None:
        log.info("no checkpoint yet; running a full harvest")
    full = since is None

    if solr is None and not dry_run:
        import pysolr  # imported here so tests and dry runs don't need a Solr client
        solr = pysolr.Solr(cfg["solr_url"], timeout=120)
    writer = SolrWriter(solr, batch_size=int(settings.get("batch_size", 500)), dry_run=dry_run)

    docs, rejected, removals, indexed_refs = [], 0, [], set()
    for item in harvest(settings, source, since=since, client=client, dry_run=dry_run,
                        refresh_thumbnails=refresh_thumbnails):
        if isinstance(item, Deletion):
            removals.append(item.id)
            log.debug("remove %s: %s", item.id, item.reason)
            if len(removals) >= writer.batch_size:
                writer.delete_ids(removals)
                removals = []
            continue
        try:
            doc = item.to_solr(run_id)
        except RecordError as e:
            rejected += 1
            log.warning("skipped: %s", e)
            continue
        writer.add([doc])
        if item.preservica_ref:
            indexed_refs.add(item.preservica_ref.lower())
        if backup_dir:
            docs.append(doc)
    writer.delete_ids(removals)

    # Only a full harvest can tell which records are gone; incremental runs rely on
    # the deletions Preservica reports.
    do_sweep = sweep and full and not rejected_too_many(rejected, writer.added)
    swept = writer.finish(source, run_id, sweep=do_sweep,
                          max_delete_fraction=float(settings.get("max_delete_fraction", 0.2)),
                          allow_large_delete=allow_large_delete)
    if do_sweep and not dry_run and settings.get("thumbnails"):
        from .preservica.thumbnails import prune
        prune(settings["thumbnail_dir"], indexed_refs)
    if not dry_run:
        write_checkpoint(cfg, started)
    if backup_dir:
        backup_dir.mkdir(parents=True, exist_ok=True)
        out = backup_dir / f"{run_id}.json"
        out.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("backup written to %s", out)
    summary = {"run_id": run_id, "mode": "full" if full else f"since {since}",
               "indexed": writer.added, "removed": writer.deleted, "swept": swept,
               "rejected": rejected, "dry_run": dry_run}
    log.info("done: %s", summary)
    return summary


def check(cfg: dict, client=None) -> int:
    """Log in, call Identify, and list the metadata formats one asset carries."""
    from .preservica import PreservicaClient
    from .preservica.oai import first_identifier, identify, list_metadata_formats
    from .preservica.hierarchy import parse_entity

    settings = cfg["preservica"]
    client = client or PreservicaClient(settings)
    info = identify(client)
    print(f"Repository:  {info.get('repositoryName', '?')}")
    print(f"Earliest:    {info.get('earliestDatestamp', '?')}")
    print(f"Deletions:   {info.get('deletedRecord', '?')}")
    ident = first_identifier(client)
    if not ident:
        print("No assets are visible to this account.")
        return 1
    formats = [f["prefix"] for f in list_metadata_formats(client, ident)]
    print(f"Sample asset {ident} carries: {', '.join(formats) or 'nothing'}")
    wanted = settings.get("metadata_prefix")
    wanted = [wanted] if isinstance(wanted, str) else list(wanted or [])
    missing = [p for p in wanted if p not in formats]
    if missing:
        print(f"  note: configured metadata_prefix {missing} isn't on this asset; "
              "assets without it are skipped unless another prefix is listed")
    if settings.get("resolve_hierarchy", True):
        e = parse_entity(client.entity("io", ident.split(":")[-1]), "io", ident.split(":")[-1])
        print(f"Entity API:  ok (security tag {e.security_tag!r}, parent {e.parent})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingest", description="Harvest Preservica into the Blacklight Solr index.")
    ap.add_argument("--config", default="config.yaml", help="config file (default: config.yaml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="test the connection and show which metadata formats an asset carries")
    r = sub.add_parser("run", help="harvest Preservica into Solr")
    r.add_argument("--incremental", action="store_true", help="harvest only changes since the last successful run")
    r.add_argument("--dry-run", action="store_true", help="harvest and map, but don't write to Solr or download thumbnails")
    r.add_argument("--backup-dir", type=Path, help="also write the Solr documents to this folder as JSON")
    r.add_argument("--no-sweep", action="store_true", help="don't remove records missing from a full harvest")
    r.add_argument("--allow-large-delete", action="store_true",
                   help="allow the sweep to remove more than max_delete_fraction of the index")
    r.add_argument("--refresh-thumbnails", action="store_true", help="download every thumbnail again")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    try:
        if args.cmd == "check":
            return check(cfg)
        run(cfg, dry_run=args.dry_run, backup_dir=args.backup_dir, allow_large_delete=args.allow_large_delete,
            sweep=not args.no_sweep, incremental=args.incremental, refresh_thumbnails=args.refresh_thumbnails)
    except Exception as e:
        log.error("failed: %s", e)
        if args.verbose:
            raise
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
