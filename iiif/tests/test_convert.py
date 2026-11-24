from types import SimpleNamespace

from conftest import make_image
from preservica_iiif.convert import process, withdraw
from preservica_iiif.repository import Repository


def setup_tree(repo, images, tag="open", folder_tag="open", meta=None, n=1):
    files = [(f"page{i}.jpg", make_image(images / f"p{i}.jpg", 900, 600)) for i in range(1, n + 1)]
    repo.add("folder", "top", tag=folder_tag)
    repo.add("folder", "coll", parent="top")
    repo.add("asset", "a1", parent="coll", tag=tag, title="Photo", files=files,
             meta=meta or {"title": "Sandbagging", "coordinates": [(42.5, -92.4)]})
    return files


def test_publishes_tiles_and_manifest(repo, store, settings, images):
    setup_tree(repo, images, n=2)
    r = process("a1", repo, store, settings)
    assert r.status == "published"
    assert store.list_tiles("a1_") == ["a1_0001.tif", "a1_0002.tif"]
    m = store.get_json("manifests/a1.json")
    assert m["label"] == {"none": ["Sandbagging"]} and len(m["items"]) == 2
    assert m["navPlace"]["features"][0]["geometry"]["coordinates"] == [-92.4, 42.5]
    assert m["homepage"][0]["id"] == "https://portal.example.edu/asset/a1"


def test_unchanged_files_are_not_converted_again(repo, store, settings, images):
    setup_tree(repo, images)
    process("a1", repo, store, settings)
    assert process("a1", repo, store, settings).status == "unchanged"
    assert repo.downloads == 1
    assert process("a1", repo, store, settings, force=True).status == "published"


def test_metadata_changes_update_the_manifest_without_reconverting(repo, store, settings, images):
    setup_tree(repo, images)
    process("a1", repo, store, settings)
    repo.meta["a1"]["title"] = "Sandbagging on Main Street"
    assert process("a1", repo, store, settings).status == "published"
    assert store.get_json("manifests/a1.json")["label"] == {"none": ["Sandbagging on Main Street"]}
    assert repo.downloads == 1                               # the images weren't converted again
    repo.meta["a1"]["restricted"] = True                    # restricted later, tag unchanged
    assert process("a1", repo, store, settings).status == "withdrawn"


def test_lost_pages_are_removed(repo, store, settings, images):
    setup_tree(repo, images, n=3)
    process("a1", repo, store, settings)
    repo.file_map["a1"] = repo.file_map["a1"][:1]
    process("a1", repo, store, settings)
    assert store.list_tiles("a1_") == ["a1_0001.tif"]


def test_closed_asset_is_withdrawn(repo, store, settings, images):
    setup_tree(repo, images)
    process("a1", repo, store, settings)
    repo.entities["a1"].security_tag = "closed"
    assert process("a1", repo, store, settings).status == "withdrawn"
    assert store.list_tiles("a1_") == [] and store.get_json("manifests/a1.json") is None


def test_closed_folder_above_hides_the_asset(repo, store, settings, images):
    setup_tree(repo, images, folder_tag="closed")
    assert process("a1", repo, store, settings).status == "withdrawn"
    assert repo.downloads == 0


def test_mods_restriction_is_respected(repo, store, settings, images):
    setup_tree(repo, images, meta={"title": "x", "restricted": True})
    assert process("a1", repo, store, settings).status == "withdrawn"
    assert repo.downloads == 0


def test_deleted_asset_is_withdrawn(repo, store, settings, images):
    setup_tree(repo, images)
    process("a1", repo, store, settings)
    del repo.entities["a1"]
    assert process("a1", repo, store, settings).status == "withdrawn"
    assert store.get_json("manifests/a1.json") is None


def test_non_images_are_skipped_with_a_note(repo, store, settings, images):
    pdf = images / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    repo.add("asset", "doc", files=[("report.pdf", pdf)])
    r = process("doc", repo, store, settings)
    assert r.status == "skipped" and ".pdf" in r.detail
    assert store.get_json("status/doc.json")["status"] == "skipped"
    assert store.get_json("manifests/doc.json") is None


def test_large_files_are_left_for_the_cli(repo, store, settings, images):
    setup_tree(repo, images)
    settings.max_source_bytes = 10
    assert process("a1", repo, store, settings).status == "too_large"
    assert repo.downloads == 0


def test_folder_event_queues_its_assets(repo, store, settings, images):
    setup_tree(repo, images)
    repo.add("asset", "a2", parent="coll")
    queued = []
    r = process("top", repo, store, settings, enqueue=queued.extend)
    assert r.status == "expanded" and sorted(queued) == ["a1", "a2"]


def test_withdraw_is_quiet_for_unknown_refs(store, settings):
    assert withdraw("nothing", store, settings, "test").status == "withdrawn"


def test_repository_prefers_access_then_preservation():
    def rep(kind, name):
        return SimpleNamespace(rep_type=SimpleNamespace(value=kind), name=name)

    def gen(active, fname):
        return SimpleNamespace(active=active, bitstreams=[SimpleNamespace(filename=fname, length=5, fixity={"MD5": "x"})])

    reps = {"A": rep("Access", "A"), "P": rep("Preservation", "P")}
    cos = {"A": [SimpleNamespace(reference="co-a")], "P": [SimpleNamespace(reference="co-p")]}
    gens = {"co-a": [gen(False, "old.jpg"), gen(True, "access.jpg")], "co-p": [gen(True, "master.tif")]}
    api = SimpleNamespace(asset=lambda ref: ref, representations=lambda a: list(reps.values()) if a == "both" else [reps["P"]],
                          content_objects=lambda r: cos[r.name], generations=lambda co: gens[co.reference])
    r = Repository(api)
    assert [f.filename for f in r.files("both", ["Access", "Preservation"])] == ["access.jpg"]
    assert [f.filename for f in r.files("pres", ["Access", "Preservation"])] == ["master.tif"]
    assert r.files("pres", ["Access"]) == []
