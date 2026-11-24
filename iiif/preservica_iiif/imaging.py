"""Turn a source image into the tiled, pyramidal TIFF that serverless-iiif serves.

libvips (through pyvips) streams the image, so memory stays low even for large scans.
"""
from __future__ import annotations

from functools import lru_cache

# Formats we convert. Others (PDF, audio, video, documents) keep the hand-off to Preservica.
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff", ".png", ".jp2", ".j2k", ".jpx", ".gif", ".webp"}


@lru_cache(maxsize=1)
def readable_suffixes() -> frozenset[str]:
    """IMAGE_SUFFIXES that this libvips build can open (JPEG 2000 needs openjpeg, as in the container)."""
    import pyvips

    return frozenset(s for s in IMAGE_SUFFIXES if s in set(pyvips.get_suffixes()) or
                     (s in {".jp2", ".j2k", ".jpx"} and pyvips.type_find("VipsForeign", "jp2kload") != 0))


def can_convert(suffix: str) -> bool:
    return suffix.lower() in readable_suffixes()


def _to_srgb(img):
    """8-bit sRGB or greyscale, no alpha, upright: what a JPEG-compressed tile can hold."""
    try:
        if img.get_typeof("orientation") and img.get("orientation") not in (0, 1):
            img = img.autorot()
    except Exception:
        pass
    if img.hasalpha():
        img = img.flatten(background=[255] * (img.bands - 1))
    grey = img.interpretation in ("b-w", "grey16")
    if img.interpretation == "cmyk" or img.get_typeof("icc-profile-data"):
        try:
            img = img.icc_transform("srgb")
            grey = False
        except Exception:
            img = img.colourspace("srgb")
            grey = False
    target = "b-w" if grey else "srgb"
    if img.interpretation != target or img.format != "uchar":
        img = img.colourspace(target)
    if img.format != "uchar":
        img = img.cast("uchar")
    if img.bands > (1 if grey else 3):
        img = img.extract_band(0, n=1 if grey else 3)
    return img


def to_pyramid_tiff(src: str, dst: str, tile: int = 256, quality: int = 90) -> tuple[int, int]:
    """Write `dst` and return (width, height). Multi-page sources: the first page only."""
    import pyvips

    img = _to_srgb(pyvips.Image.new_from_file(src))
    opts = dict(tile=True, pyramid=True, compression="jpeg", Q=quality, tile_width=tile, tile_height=tile,
                bigtiff=img.width * img.height * img.bands > 3_000_000_000)
    try:
        img.tiffsave(dst, keep=0, **opts)        # libvips 8.15+: drop EXIF/XMP
    except pyvips.Error:
        img.tiffsave(dst, strip=True, **opts)    # older libvips (e.g. Debian bookworm)
    return img.width, img.height
