"""Write records to Solr in batches and remove records a source no longer has."""
from __future__ import annotations

import logging
from typing import Iterable, Protocol

log = logging.getLogger(__name__)


class SolrLike(Protocol):
    def add(self, docs, commit=False, **kw): ...
    def delete(self, id=None, q=None, commit=False, **kw): ...
    def commit(self, **kw): ...
    def search(self, q, **kw): ...


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class SolrWriter:
    """Batches adds and, after a complete harvest, deletes the source's records this run didn't touch.

    The sweep is what removes withdrawn, deleted or newly restricted items. It only
    runs when the caller says the harvest was complete, and it refuses to delete
    more than ``max_delete_fraction`` of a source's records, so a broken API
    response can't empty the index.
    """

    def __init__(self, solr: SolrLike | None, *, batch_size: int = 500, dry_run: bool = False):
        self.solr = solr
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.added = 0
        self.deleted = 0
        self._batch: list[dict] = []

    def add(self, docs: Iterable[dict]) -> None:
        for doc in docs:
            self._batch.append(doc)
            if len(self._batch) >= self.batch_size:
                self._flush()

    def delete_ids(self, ids: list[str]) -> int:
        """Remove specific records (deletions reported by the source). Unknown ids are harmless."""
        self._flush()  # an add and a delete of the same id must reach Solr in order
        ids = [i for i in ids if i]
        if ids and not self.dry_run:
            self.solr.delete(id=ids, commit=False)
        self.deleted += len(ids)
        return len(ids)

    def _flush(self) -> None:
        if not self._batch:
            return
        if not self.dry_run:
            self.solr.add(self._batch, commit=False)
        self.added += len(self._batch)
        log.info("sent %d documents (%d total)", len(self._batch), self.added)
        self._batch = []

    def count(self, q: str) -> int:
        if self.solr is None:
            return 0
        return int(self.solr.search(q, rows=0).hits)

    def finish(self, source: str, run_id: str, *, sweep: bool, max_delete_fraction: float = 0.2,
               allow_large_delete: bool = False) -> int:
        """Flush, optionally sweep stale records, commit. Returns the number of records deleted."""
        self._flush()
        deleted = 0
        if sweep:
            stale_q = f"source_ssi:{_q(source)} AND -ingest_run_ssi:{_q(run_id)}"
            total = self.count(f"source_ssi:{_q(source)}")
            stale = self.count(stale_q)
            if stale:
                fraction = stale / total if total else 1.0
                if fraction > max_delete_fraction and not allow_large_delete:
                    raise RuntimeError(
                        f"refusing to delete {stale} of {total} '{source}' records ({fraction:.0%}); "
                        f"limit is {max_delete_fraction:.0%}. Check the harvest, then rerun with "
                        "--allow-large-delete if this is expected.")
                if not self.dry_run:
                    self.solr.delete(q=stale_q, commit=False)
                deleted = stale
                log.info("removed %d stale '%s' records", stale, source)
        if not self.dry_run and self.solr is not None:
            self.solr.commit()
        return deleted
