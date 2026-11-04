"""Shrinking an imported image (docs/ready-to-build/folder-import-and-file-previews.md, Images
compressed): at most the chosen size on its longest side, saved again at a high quality,
turned upright, without its photo data (location, camera). Only reads the bytes it is given."""

from __future__ import annotations

import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.exception_capture import CapturedExceptionContext
from app.utils.sampling import spread_sample

# The longest sides a compressed image may keep (the maintainer, 2026-11-01: chosen by size,
# each shown with what it comes to; 2560, sharp full-screen, at first).
HD_SIDE_PX = 1280
FULL_HD_SIDE_PX = 1920
SHARP_FULL_SCREEN_SIDE_PX = 2560
ULTRA_HD_SIDE_PX = 3840
IMAGE_LONGEST_SIDES = (HD_SIDE_PX, FULL_HD_SIDE_PX, SHARP_FULL_SCREEN_SIDE_PX, ULTRA_HD_SIDE_PX)
JPEG_QUALITY = 82
WEBP_QUALITY = 82
# The images compression shrinks: GIF, SVG, HEIC and AVIF come in unchanged.
COMPRESSIBLE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"})
# How many images an estimate compresses (at each size): spread from the smallest to the largest.
ESTIMATE_SAMPLE_COUNT = 8
# Images an estimate compresses at once (each holds a decoded picture in memory).
_ESTIMATE_THREADS = 4

_JPEG = "JPEG"
_PNG = "PNG"
_WEBP = "WEBP"
_KEPT_FORMATS = frozenset({_JPEG, _PNG, _WEBP})
# TIFF and BMP come in as JPEG, or PNG when they have transparency.
_CONVERTED_FORMATS = frozenset({"TIFF", "BMP"})
_CONVERTED_SUFFIXES = frozenset({".tif", ".tiff", ".bmp"})
_SUFFIX_OF_FORMAT = {_JPEG: ".jpg", _PNG: ".png"}
_MIME_OF_FORMAT = {_JPEG: "image/jpeg", _PNG: "image/png", _WEBP: "image/webp"}
_ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})
_TRANSPARENCY = "transparency"
_ICC_PROFILE = "icc_profile"
_CMYK = "CMYK"
_GREY = "L"
_SINGLE_FRAME = 1


@dataclass(frozen=True)
class ImageChoice:
    """How an import's images come in: compressed or as they are, and the longest side a
    compressed one keeps (chosen even when not compressing: the screen keeps it)."""

    compresses: bool
    longest_side_px: int

    def __post_init__(self) -> None:
        if self.longest_side_px not in IMAGE_LONGEST_SIDES:
            raise ValueError(f"longest_side_px must be one of {IMAGE_LONGEST_SIDES}: {self.longest_side_px}")


@dataclass(frozen=True)
class CompressedImage:
    content: bytes
    # The file's name, its ending changed when its format was (TIFF and BMP).
    filename: str
    mime_type: str


@dataclass(frozen=True)
class _Shrunk:
    # None when the image is not one compression shrinks (its format, or animated).
    content: bytes | None
    image_format: str


_NOT_SHRUNK = _Shrunk(content=None, image_format="")


def compressed_image(content: bytes, filename: str, *, longest_side_px: int) -> CompressedImage | None:
    """The image in content compressed to at most longest_side_px on its longest side, or
    None to keep the original: not an image this shrinks, one it can't read, or one no
    smaller compressed."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if longest_side_px not in IMAGE_LONGEST_SIDES:
        raise ValueError(f"longest_side_px must be one of {IMAGE_LONGEST_SIDES}: {longest_side_px}")
    name = PurePosixPath(filename)
    if name.suffix.casefold() not in COMPRESSIBLE_SUFFIXES:
        return None
    # The user's files: one that isn't a readable image comes in as it is.
    image_capture = CapturedExceptionContext(
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    boundary='app/services/image_compression.py:compressed_image:image_capture')
    shrunk: _Shrunk | None = None
    with image_capture:
        shrunk = _shrunk(content, longest_side_px)
    if image_capture.captured_exception is not None:
        return None
    if shrunk is None:
        raise RuntimeError("Image compression returned without a result or exception")
    if shrunk.content is None or len(shrunk.content) >= len(content):
        return None
    if shrunk.image_format in _SUFFIX_OF_FORMAT and name.suffix.casefold() in _CONVERTED_SUFFIXES:
        name = name.with_suffix(_SUFFIX_OF_FORMAT[shrunk.image_format])
    return CompressedImage(content=shrunk.content, filename=name.name, mime_type=_MIME_OF_FORMAT[shrunk.image_format])


def estimated_compressed_bytes(files: List[Tuple[Path, int]]) -> Dict[int, int]:
    """About how many bytes the images at files ((path, size) pairs) take compressed, at each
    of IMAGE_LONGEST_SIDES: a few of them compressed, from the smallest to the largest, and
    the rest taken to shrink alike. Exact when there are no more than ESTIMATE_SAMPLE_COUNT."""
    if not files:
        return {side: 0 for side in IMAGE_LONGEST_SIDES}
    by_size = sorted(files, key=lambda pair: pair[1])
    sample = spread_sample(by_size, ESTIMATE_SAMPLE_COUNT)
    before = sum(size for _path, size in sample)
    total = sum(size for _path, size in by_size)
    jobs = [(path, size, side) for side in IMAGE_LONGEST_SIDES for path, size in sample]
    with ThreadPoolExecutor(max_workers=_ESTIMATE_THREADS) as executor:
        sizes = list(executor.map(lambda job: _compressed_size(*job), jobs))
    after_by_side = {side: 0 for side in IMAGE_LONGEST_SIDES}
    for (_path, _size, side), compressed_size in zip(jobs, sizes):
        after_by_side[side] += compressed_size
    if before == 0:
        return {side: total for side in IMAGE_LONGEST_SIDES}
    return {side: round(total * after / before) for side, after in after_by_side.items()}


def _compressed_size(path: Path, size: int, longest_side_px: int) -> int:
    compressed = compressed_image(path.read_bytes(), path.name, longest_side_px=longest_side_px)
    if compressed is None:
        return size
    return len(compressed.content)


def _shrunk(content: bytes, longest_side_px: int) -> _Shrunk:
    with warnings.catch_warnings():
        # Pillow's own limit still refuses an image too large to open (DecompressionBombError).
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as image:
            source_format = image.format
            if source_format not in _KEPT_FORMATS | _CONVERTED_FORMATS:
                return _NOT_SHRUNK
            if hasattr(image, "n_frames") and image.n_frames > _SINGLE_FRAME:
                return _NOT_SHRUNK
            if source_format == _JPEG:
                # Decoded at a smaller scale when it is far larger than needed: much faster.
                image.draft(image.mode, _fitted_size(image.size, longest_side_px))
            upright = ImageOps.exif_transpose(image)
    has_alpha = any((upright.mode in _ALPHA_MODES, _TRANSPARENCY in upright.info))
    output_format = source_format
    if source_format in _CONVERTED_FORMATS:
        output_format = _JPEG
        if has_alpha:
            output_format = _PNG
    mode = "RGB"
    if has_alpha:
        mode = "RGBA"
    elif upright.mode == _GREY:
        mode = _GREY
    working = upright
    if upright.mode != mode:
        working = upright.convert(mode)
    working.thumbnail((longest_side_px, longest_side_px), Image.Resampling.LANCZOS)
    # Only what draws the picture is saved: no photo data (location, camera, XMP).
    options: dict[str, object] = {}
    if _ICC_PROFILE in upright.info and upright.mode != _CMYK:
        options[_ICC_PROFILE] = upright.info[_ICC_PROFILE]
    if output_format == _JPEG:
        options.update(quality=JPEG_QUALITY, optimize=True, progressive=True)
    elif output_format == _WEBP:
        options.update(quality=WEBP_QUALITY)
    else:
        options.update(optimize=True)
    out = BytesIO()
    working.save(out, output_format, **options)
    return _Shrunk(content=out.getvalue(), image_format=output_format)


def _fitted_size(size: Tuple[int, int], longest_side_px: int) -> Tuple[int, int]:
    """size made to fit longest_side_px on its longest side (never larger)."""
    width, height = size
    longest = max(width, height)
    if longest <= longest_side_px:
        return size
    return (max(1, width * longest_side_px // longest), max(1, height * longest_side_px // longest))
