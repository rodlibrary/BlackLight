import pytest

from conftest import make_image
from preservica_iiif.convert import process
from preservica_iiif.reconcile import TooManyWithdrawals, reconcile, write_index


def tree(repo, images):
    img = [("p.jpg", make_image(images / "p.jpg", 300, 200))]
    repo.add("folder", "ir")
    repo.add("folder", "scua")
    repo.add("folder", "closed-box", parent="scua", tag="closed")
    for ref, parent in (("a1", "ir"), ("a2", "scua"), ("hidden", "closed-box")):
        repo.add("asset", ref, parent=parent, files=img)
    repo.add("asset", "a3", parent="scua", tag="closed", files=img)


def test_queues_missing_and_prunes_closed_folders(repo, store, settings, images):
    tree(repo, images)
    queued = []
    s = reconcile(repo, store, settings, queued.extend)
    assert sorted(queued) == ["a1", "a2"] and s.public_assets == 2


def test_existing_manifests_and_skip_notes_are_not_requeued(repo, store, settings, images):
    tree(repo, images)
    process("a1", repo, store, settings)
    store.put_json("status/a2.json", {}, {"pipeline-version": "1"})
    queued = []
    reconcile(repo, store, settings, queued.extend)
    assert queued == []
    reconcile(repo, store, settings, queued.extend, recheck_all=True)
    assert sorted(queued) == ["a1", "a2"]


def test_withdraws_manifests_that_are_no_longer_public(repo, store, settings, images):
    tree(repo, images)
    for ref in ("a1", "a2"):
        process(ref, repo, store, settings)
    repo.entities["a2"].security_tag = "closed"
    settings.max_delete_fraction = 0.5
    s = reconcile(repo, store, settings, lambda refs: None)
    assert s.withdrawn == ["a2"] and store.get_json("manifests/a2.json") is None
    assert write_index(store, settings) == ["a1"]
    assert store.get_json("manifests/index.json") == {"manifests": ["a1"]}
    assert reconcile(repo, store, settings, lambda refs: None).withdrawn == []     # the index isn't an item


def test_guard_against_mass_withdrawal(repo, store, settings, images):
    tree(repo, images)
    for ref in ("a1", "a2"):
        process(ref, repo, store, settings)
    repo.entities["ir"].security_tag = "closed"
    with pytest.raises(TooManyWithdrawals):
        reconcile(repo, store, settings, lambda refs: None)
    assert store.get_json("manifests/a1.json") is not None
    assert reconcile(repo, store, settings, lambda refs: None, allow_large_withdrawal=True).withdrawn == ["a1"]


def test_dry_run_changes_nothing(repo, store, settings, images):
    tree(repo, images)
    process("a1", repo, store, settings)
    repo.entities["a1"].security_tag = "closed"
    queued = []
    s = reconcile(repo, store, settings, queued.extend, dry_run=True, allow_large_withdrawal=True)
    assert s.withdrawn == ["a1"] and queued == [] and store.get_json("manifests/a1.json") is not None


def test_root_folders_limit_the_walk(repo, store, settings, images):
    tree(repo, images)
    settings.root_folders = ["ir"]
    queued = []
    reconcile(repo, store, settings, queued.extend)
    assert queued == ["a1"]
