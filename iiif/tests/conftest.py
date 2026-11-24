import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "iiif"):           # the ingest package and preservica_iiif
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from preservica_iiif.repository import EntityInfo, SourceFile  # noqa: E402
from preservica_iiif.settings import Settings  # noqa: E402
from preservica_iiif.storage import LocalStore  # noqa: E402


def make_image(path, width=600, height=400, bands=3, **kw):
    import pyvips

    img = (pyvips.Image.black(width, height, bands=bands) + [60] * bands).cast("uchar")
    for k, v in kw.items():
        img = img.copy(**{k: v})
    img.write_to_file(str(path))
    return path


class FakeRepo:
    """Folders and assets in memory; `files` maps asset ref -> list of (filename, local path)."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.entities: dict[str, EntityInfo] = {}
        self.kids: dict[str | None, list[tuple[str, str]]] = {}
        self.file_map: dict[str, list[tuple[str, Path]]] = {}
        self.meta: dict[str, dict] = {}
        self.downloads = 0

    def add(self, kind, ref, parent=None, tag="open", title=None, files=(), meta=None):
        self.entities[ref] = EntityInfo(ref, kind, title or ref.title(), "", tag, parent)
        self.kids.setdefault(parent, []).append((kind, ref))
        if kind == "asset":
            self.file_map[ref] = list(files)
            self.meta[ref] = meta or {}
        return self

    def asset(self, ref):
        e = self.entities.get(ref)
        return e if e and e.kind == "asset" else None

    def folder(self, ref):
        e = self.entities.get(ref)
        return e if e and e.kind == "folder" else None

    def children(self, ref):
        return iter(self.kids.get(ref, []))

    def metadata(self, ref):
        return dict(self.meta.get(ref, {}))

    def files(self, ref, order):
        return [SourceFile(f"{ref}-co{n}", name, path.stat().st_size, {"SHA256": f"{name}:{path.stat().st_size}"},
                           "Access", path) for n, (name, path) in enumerate(self.file_map.get(ref, []), 1)]

    def download(self, f, dest):
        self.downloads += 1
        Path(dest).write_bytes(Path(f.handle).read_bytes())


@pytest.fixture
def settings():
    return Settings(public_base_url="https://iiif.example.edu/",
                    landing_url_template="https://portal.example.edu/asset/{uuid}")


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path / "out")


@pytest.fixture
def repo(tmp_path):
    return FakeRepo(tmp_path)


@pytest.fixture
def images(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    return d
