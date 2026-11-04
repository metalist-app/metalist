"""Compressing imported images (docs/ready-to-build/folder-import-and-file-previews.md,
Images compressed): the acceptance checks agreed before the code, (4) to (8)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from app.services.image_compression import IMAGE_LONGEST_SIDES, compressed_image, estimated_compressed_bytes

# A photo larger than compression keeps: 4000 by 3000, as a 12-megapixel camera takes.
PHOTO_SIZE = (4000, 3000)
NOISE_SIGMA = 40
ORIGINAL_QUALITY = 95
# EXIF orientation 6: stored sideways, shown turned a quarter clockwise.
SIDEWAYS = 6
# A small photo saved at a low quality: saved again at compression's quality it would grow.
SMALL_SIZE = (120, 90)
# The size chosen at first: sharp full-screen.
LONGEST_SIDE_PX = 2560
SMALL_QUALITY = 50


def _photo(size: tuple[int, int], *, exif: Image.Exif | None) -> bytes:
    picture = Image.merge("RGB", [Image.effect_noise(size, NOISE_SIGMA) for _band in range(3)])
    out = BytesIO()
    if exif is None:
        picture.save(out, "JPEG", quality=ORIGINAL_QUALITY)
    else:
        picture.save(out, "JPEG", quality=ORIGINAL_QUALITY, exif=exif)
    return out.getvalue()


def _small_photo() -> bytes:
    picture = Image.merge("RGB", [Image.effect_noise(SMALL_SIZE, NOISE_SIGMA) for _band in range(3)])
    out = BytesIO()
    picture.save(out, "JPEG", quality=SMALL_QUALITY)
    return out.getvalue()


def _opened(content: bytes) -> Image.Image:
    image = Image.open(BytesIO(content))
    image.load()
    return image


def _saved(image: Image.Image, image_format: str) -> bytes:
    out = BytesIO()
    image.save(out, image_format)
    return out.getvalue()


def test_a_large_photo_comes_in_at_most_2560_on_its_longest_side_and_smaller() -> None:
    original = _photo(PHOTO_SIZE, exif=None)
    compressed = compressed_image(original, "photo.JPG", longest_side_px=LONGEST_SIDE_PX)
    assert compressed is not None
    assert _opened(compressed.content).size == (LONGEST_SIDE_PX, LONGEST_SIDE_PX * 3 // 4)
    assert len(compressed.content) < len(original)
    assert (compressed.filename, compressed.mime_type) == ("photo.JPG", "image/jpeg")


def test_a_sideways_photo_comes_in_upright_without_its_location_or_camera() -> None:
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = SIDEWAYS
    exif[ExifTags.Base.Model] = "Camera X"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (52.0, 22.0, 0.0)
    original = _photo(PHOTO_SIZE, exif=exif)
    assert len(_opened(original).getexif()) > 0
    compressed = compressed_image(original, "photo.jpg", longest_side_px=LONGEST_SIDE_PX)
    assert compressed is not None
    image = _opened(compressed.content)
    # Stored 4000 wide and 3000 high, shown turned: now 2560 high.
    assert image.size == (LONGEST_SIDE_PX * 3 // 4, LONGEST_SIDE_PX)
    assert len(image.getexif()) == 0
    assert "exif" not in image.info and "xmp" not in image.info


def test_an_image_no_smaller_compressed_comes_in_unchanged() -> None:
    assert compressed_image(_small_photo(), "small.jpg", longest_side_px=LONGEST_SIDE_PX) is None


def test_formats_compression_leaves_alone_come_in_unchanged() -> None:
    photo = _photo(PHOTO_SIZE, exif=None)
    for name in ("photo.gif", "photo.svg", "photo.heic", "photo.avif"):
        assert compressed_image(photo, name, longest_side_px=LONGEST_SIDE_PX) is None
    frames = [Image.new("RGB", PHOTO_SIZE, colour) for colour in ("red", "blue")]
    out = BytesIO()
    frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:])
    assert compressed_image(out.getvalue(), "moving.webp", longest_side_px=LONGEST_SIDE_PX) is None


def test_an_image_that_cant_be_read_comes_in_as_it_is() -> None:
    assert compressed_image(b"not a picture", "broken.jpg", longest_side_px=LONGEST_SIDE_PX) is None
    assert compressed_image(_photo(PHOTO_SIZE, exif=None)[:1000], "cut.jpg", longest_side_px=LONGEST_SIDE_PX) is None


def test_a_tiff_comes_in_as_jpeg_and_one_with_transparency_as_png() -> None:
    opaque = Image.merge("RGB", [Image.effect_noise(PHOTO_SIZE, NOISE_SIGMA) for _band in range(3)])
    compressed = compressed_image(_saved(opaque, "TIFF"), "scan.tiff", longest_side_px=LONGEST_SIDE_PX)
    assert compressed is not None
    assert (compressed.filename, compressed.mime_type) == ("scan.jpg", "image/jpeg")
    see_through = opaque.convert("RGBA")
    compressed = compressed_image(_saved(see_through, "TIFF"), "logo.tif", longest_side_px=LONGEST_SIDE_PX)
    assert compressed is not None
    assert (compressed.filename, compressed.mime_type) == ("logo.png", "image/png")
    assert _opened(compressed.content).mode == "RGBA"


def test_the_estimate_is_exact_for_a_few_images(tmp_path: Path) -> None:
    photo = _photo(PHOTO_SIZE, exif=None)
    tiny = _small_photo()
    (tmp_path / "photo.jpg").write_bytes(photo)
    (tmp_path / "small.jpg").write_bytes(tiny)
    compressed = compressed_image(photo, "photo.jpg", longest_side_px=LONGEST_SIDE_PX)
    assert compressed is not None
    files = [(tmp_path / "photo.jpg", len(photo)), (tmp_path / "small.jpg", len(tiny))]
    estimate = estimated_compressed_bytes(files)
    assert sorted(estimate) == list(IMAGE_LONGEST_SIDES)
    assert estimate[LONGEST_SIDE_PX] == len(compressed.content) + len(tiny)
    # A smaller longest side comes to less.
    assert estimate[1280] < estimate[1920] < estimate[2560]
    assert estimated_compressed_bytes([]) == {side: 0 for side in IMAGE_LONGEST_SIDES}


# The size is chosen (the maintainer, 2026-11-01): each longest side the screen offers.
def test_each_offered_size_is_the_longest_side_a_photo_keeps() -> None:
    original = _photo(PHOTO_SIZE, exif=None)
    for side in IMAGE_LONGEST_SIDES:
        compressed = compressed_image(original, "photo.jpg", longest_side_px=side)
        assert compressed is not None
        assert _opened(compressed.content).size == (side, side * 3 // 4)


def test_the_largest_size_still_shrinks_a_4000_wide_photo() -> None:
    original = _photo(PHOTO_SIZE, exif=None)
    compressed = compressed_image(original, "photo.jpg", longest_side_px=3840)
    assert compressed is not None
    assert _opened(compressed.content).size == (3840, 2880)


def test_a_size_not_offered_is_refused() -> None:
    with pytest.raises(ValueError, match="longest_side_px"):
        compressed_image(b"x", "photo.jpg", longest_side_px=1000)
