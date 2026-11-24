import pyvips
import pytest

from conftest import make_image
from preservica_iiif import imaging


def _check_pyramid(path, width, height, bands):
    img = pyvips.Image.new_from_file(str(path))
    assert (img.width, img.height) == (width, height)
    assert img.bands == bands and img.format == "uchar"
    assert img.get("n-pages") > 1                       # the pyramid's levels
    assert img.get("tile-width") == 256 if img.get_typeof("tile-width") else True
    return img


def test_rgb_jpeg_becomes_tiled_pyramid(tmp_path):
    src = make_image(tmp_path / "a.jpg", 1500, 1000)
    assert imaging.to_pyramid_tiff(str(src), str(tmp_path / "a.tif")) == (1500, 1000)
    _check_pyramid(tmp_path / "a.tif", 1500, 1000, 3)


def test_alpha_is_flattened(tmp_path):
    src = make_image(tmp_path / "b.png", 800, 600, bands=4, interpretation="srgb")
    imaging.to_pyramid_tiff(str(src), str(tmp_path / "b.tif"))
    _check_pyramid(tmp_path / "b.tif", 800, 600, 3)


def test_sixteen_bit_and_greyscale(tmp_path):
    rgb16 = (pyvips.Image.black(700, 500, bands=3) + 30000).cast("ushort").copy(interpretation="rgb16")
    rgb16.write_to_file(str(tmp_path / "c.png"))
    imaging.to_pyramid_tiff(str(tmp_path / "c.png"), str(tmp_path / "c.tif"))
    _check_pyramid(tmp_path / "c.tif", 700, 500, 3)

    make_image(tmp_path / "g.png", 700, 500, bands=1, interpretation="b-w")
    imaging.to_pyramid_tiff(str(tmp_path / "g.png"), str(tmp_path / "g.tif"))
    _check_pyramid(tmp_path / "g.tif", 700, 500, 1)


def test_cmyk_tiff_becomes_srgb(tmp_path):
    make_image(tmp_path / "d.tif", 600, 600, bands=4, interpretation="cmyk")
    imaging.to_pyramid_tiff(str(tmp_path / "d.tif"), str(tmp_path / "d-out.tif"))
    _check_pyramid(tmp_path / "d-out.tif", 600, 600, 3)


CASES = [(".jpg", True), (".TIF", True), (".png", True), (".pdf", False), (".mp4", False), (".docx", False), ("", False)]


@pytest.mark.parametrize("suffix,ok", CASES)
def test_can_convert(suffix, ok):
    assert imaging.can_convert(suffix) is ok
