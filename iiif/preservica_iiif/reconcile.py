"""The nightly safety net: queue public assets that have no manifest yet, and withdraw manifests
whose assets are no longer public (or no longer exist).

It walks the folder tree from the configured roots and skips folders that aren't public, so
closed material is never even listed. Webhooks keep things current during the day; this run
catches whatever a webhook missed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .convert import PublicPolicy, withdraw
from .settings import PIPELINE_VERSION, Settings

log = logging.getLogger(__name__)


class TooManyWithdrawals(RuntimeError):
    pass


@dataclass
class Summary:
    public_assets: int = 0
    queued: list[str] = field(default_factory=list)
    withdrawn: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"public_assets": self.public_assets, "queued": len(self.queued), "withdrawn": len(self.withdrawn)}


def public_assets(repo, settings: Settings, policy: PublicPolicy):
    """Refs of public assets under the roots (or the whole repository), pruning closed folders."""
    stack: list[str | None] = list(settings.root_folders) or [None]
    for root in stack[:]:
        if root is not None and not policy.folder_public(root):
            log.warning("root folder %s isn't public; skipping it", root)
            stack.remove(root)
    while stack:
        parent = stack.pop()
        for kind, ref in repo.children(parent):
            if kind == "folder":
                info = repo.folder(ref)
                if info is not None and policy.tag_ok(info.security_tag):
                    policy._folders[ref] = True
                    stack.append(ref)
                else:
                    policy._folders[ref] = False
            else:
                info = repo.asset(ref)
                if info is not None and policy.tag_ok(info.security_tag):
                    yield ref


def reconcile(repo, store, settings: Settings, enqueue: Callable[[list[str]], None], *,
              recheck_all: bool = False, dry_run: bool = False, allow_large_withdrawal: bool = False) -> Summary:
    """`recheck_all` queues every public asset (the converter skips unchanged ones by fingerprint);
    otherwise only those without a manifest or a 'skipped' note from this pipeline version."""
    policy = PublicPolicy(repo, settings)
    summary = Summary()
    public = set()
    batch: list[str] = []
    for ref in public_assets(repo, settings, policy):
        public.add(ref)
        summary.public_assets += 1
        if not recheck_all:
            if store.head(settings.manifest_key(ref)) is not None:
                continue
            note = store.head(settings.status_key(ref))
            if note is not None and note.get("pipeline-version") == PIPELINE_VERSION:
                continue
        summary.queued.append(ref)
        batch.append(ref)
        if len(batch) >= 100 and not dry_run:
            enqueue(batch)
            batch = []
    if batch and not dry_run:
        enqueue(batch)

    published = set(published_refs(store, settings))
    stale = sorted(published - public)
    if published and len(stale) / len(published) > settings.max_delete_fraction and not allow_large_withdrawal:
        raise TooManyWithdrawals(
            f"{len(stale)} of {len(published)} manifests would be withdrawn; check the roots and the service "
            "account, then run again with --allow-large-withdrawal if this is expected")
    for ref in stale:
        summary.withdrawn.append(ref)
        if not dry_run:
            withdraw(ref, store, settings, "no longer public")

    # Assets with a 'skipped' note that are no longer public: drop the note.
    if not dry_run:
        notes = {k[len(settings.status_prefix):-len(".json")] for k in store.list_json(settings.status_prefix)}
        store.delete_json([settings.status_key(r) for r in sorted(notes - public)])
    log.info("reconcile: %s", summary.as_dict())
    return summary


INDEX = "index"


def published_refs(store, settings: Settings) -> list[str]:
    n = len(settings.manifest_prefix)
    return sorted(r for r in (k[n:-len(".json")] for k in store.list_json(settings.manifest_prefix)) if r != INDEX)


def write_index(store, settings: Settings) -> list[str]:
    """manifests/index.json: the refs that have a manifest, for the catalog ingest to read."""
    refs = published_refs(store, settings)
    store.put_json(settings.manifest_key(INDEX), {"manifests": refs})
    return refs
