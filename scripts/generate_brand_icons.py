"""Generate MetaList's icons from the mark's SVG sources in brand/ (brand/README.md).

Run: .venv/bin/python scripts/generate_brand_icons.py

Every raster, and favicon.svg, is drawn from the polygon and rects of the sources, so a
change to the mark is one edit there plus this command. tests/unit/test_brand_icons.py
fails when a committed icon no longer matches what this script draws.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
GENERATED = BRAND / "generated"
STATIC_IMG = ROOT / "app" / "static" / "img"
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"

FULL_MARK = BRAND / "metalist-mark-white.svg"
SMALL_MARK = BRAND / "metalist-mark-small-white.svg"

# An 8-bit color channel at full strength.
CHANNEL_FULL = 255
BLACK = (0, 0, 0, CHANNEL_FULL)
WHITE = (CHANNEL_FULL, CHANNEL_FULL, CHANNEL_FULL, CHANNEL_FULL)
CLEAR = (0, 0, 0, 0)

# Shapes are drawn this many times larger, then reduced, for smooth edges.
SUPERSAMPLE = 8
# The mark fills about this share of a square tile's width (brand/README.md).
TILE_MARK_WIDTH = 0.6
# A favicon shows at 16 px beside other sites' icons, which fill their square: its mark
# fills more of its tile (the maintainer, 2026-10-24). The tile still frames it on light tab bars.
FAVICON_MARK_WIDTH = 0.84
# The bars make the mark bottom-heavy, so it sits this share of the tile above center.
OPTICAL_LIFT = 0.02
# A maskable icon may be cut to a circle 80% of its side: a smaller mark keeps every
# corner inside it.
MASKABLE_MARK_WIDTH = 0.55
# Android's adaptive foreground is cropped to a 66 dp circle of its 108 dp canvas.
ADAPTIVE_MARK_WIDTH = 0.46
# The favicon's black tile has rounded corners: this share of its side.
FAVICON_CORNER = 0.2
# A browser tab, a high-resolution tab, and Windows' desktop shortcut.
FAVICON_TAB_SIZE = 16
FAVICON_RETINA_TAB_SIZE = 32
FAVICON_SHORTCUT_SIZE = 48
FAVICON_SIZES = (FAVICON_TAB_SIZE, FAVICON_RETINA_TAB_SIZE, FAVICON_SHORTCUT_SIZE)
# favicon.svg draws on a square of this many units.
FAVICON_SVG_UNITS = 100
# Decimals kept for coordinates written into favicon.svg.
SVG_DECIMALS = 3

APPLE_TOUCH_SIZE = 180
MANIFEST_SIZE = 192
LARGE_ICON_SIZE = 512
STORE_MASTER_SIZE = 1024
# Android's adaptive foreground at xxxhdpi: 108 dp at 4 pixels per dp.
ADAPTIVE_FOREGROUND_SIZE = 432
MARK_PNG_WIDTHS = (LARGE_ICON_SIZE, STORE_MASTER_SIZE)
# Free space is shared equally by the two sides of a centered mark.
SIDES = 2


@dataclass(frozen=True, slots=True)
class Mark:
    """A mark source: its viewBox size and its shapes as polygons in viewBox units."""
    width: float
    height: float
    polygons: tuple[tuple[tuple[float, float], ...], ...]


def read_mark(path: Path) -> Mark:
    root = ElementTree.parse(path).getroot()
    if root.tag != f"{SVG_NAMESPACE}svg":
        raise ValueError(f"{path} is not an SVG")
    min_x, min_y, width, height = (float(value) for value in root.attrib["viewBox"].split())
    if (min_x, min_y) != (0, 0):
        raise ValueError(f"{path}: the viewBox must start at 0,0")
    polygons = []
    for shape in root:
        if shape.tag == f"{SVG_NAMESPACE}title":
            continue
        if shape.tag == f"{SVG_NAMESPACE}polygon":
            pairs = shape.attrib["points"].split()
            polygons.append(tuple((float(x), float(y)) for x, y in (pair.split(",") for pair in pairs)))
            continue
        if shape.tag == f"{SVG_NAMESPACE}rect":
            x, y = float(shape.attrib["x"]), float(shape.attrib["y"])
            right, bottom = x + float(shape.attrib["width"]), y + float(shape.attrib["height"])
            polygons.append(((x, y), (right, y), (right, bottom), (x, bottom)))
            continue
        raise ValueError(f"{path}: unsupported shape {shape.tag}")
    if not polygons:
        raise ValueError(f"{path} has no shapes")
    return Mark(width=width, height=height, polygons=tuple(polygons))


@dataclass(frozen=True, slots=True)
class Placement:
    """Where the mark goes on a canvas, in canvas pixels."""
    left: float
    top: float
    scale: float


def tile_placement(mark: Mark, side: float, mark_width_share: float) -> Placement:
    scale = side * mark_width_share / mark.width
    left = (side - mark.width * scale) / SIDES
    top = (side - mark.height * scale) / SIDES - side * OPTICAL_LIFT
    return Placement(left=left, top=top, scale=scale)


def draw(
    mark: Mark,
    *,
    size: tuple[int, int],
    placement: Placement,
    color: tuple[int, int, int, int],
    paint_background: Callable[[ImageDraw.ImageDraw, tuple[int, int]], None],
) -> Image.Image:
    large = (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE)
    image = Image.new("RGBA", large, CLEAR)
    pen = ImageDraw.Draw(image)
    paint_background(pen, large)
    scale = placement.scale * SUPERSAMPLE
    for polygon in mark.polygons:
        points = [((placement.left * SUPERSAMPLE) + x * scale, (placement.top * SUPERSAMPLE) + y * scale) for x, y in polygon]
        pen.polygon(points, fill=color)
    return image.resize(size, Image.Resampling.LANCZOS)


def no_background(pen: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    del pen, size


def black_square(pen: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    pen.rectangle((0, 0, size[0], size[1]), fill=BLACK)


def black_rounded_tile(pen: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    pen.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=size[0] * FAVICON_CORNER, fill=BLACK)


def square_icon(mark: Mark, side: int, mark_width_share: float) -> Image.Image:
    """The white mark on a black square, with no transparency (app stores refuse alpha)."""
    image = draw(mark, size=(side, side), placement=tile_placement(mark, side, mark_width_share),
                 color=WHITE, paint_background=black_square)
    return image.convert("RGB")


def favicon_tile(mark: Mark, side: int) -> Image.Image:
    return draw(mark, size=(side, side), placement=tile_placement(mark, side, FAVICON_MARK_WIDTH),
                color=WHITE, paint_background=black_rounded_tile)


def mark_alone(mark: Mark, width: int, color: tuple[int, int, int, int]) -> Image.Image:
    height = round(width * mark.height / mark.width)
    return draw(mark, size=(width, height), placement=Placement(left=0, top=0, scale=width / mark.width),
                color=color, paint_background=no_background)


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def ico_bytes(images: list[Image.Image]) -> bytes:
    largest = images[-1]
    buffer = io.BytesIO()
    largest.save(buffer, format="ICO", sizes=[image.size for image in images], append_images=images[:-1])
    return buffer.getvalue()


def _number(value: float) -> str:
    return f"{round(value, SVG_DECIMALS):g}"


def favicon_svg(mark: Mark) -> bytes:
    side = FAVICON_SVG_UNITS
    placement = tile_placement(mark, side, FAVICON_MARK_WIDTH)
    shapes = "\n".join(
        f'    <polygon points="{" ".join(f"{_number(x)},{_number(y)}" for x, y in polygon)}"/>'
        for polygon in mark.polygons
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}">\n'
        "  <title>MetaList</title>\n"
        "  <!-- Generated by scripts/generate_brand_icons.py from brand/metalist-mark-small-white.svg. -->\n"
        f'  <rect width="{side}" height="{side}" rx="{_number(side * FAVICON_CORNER)}" fill="#000000"/>\n'
        f'  <g fill="#ffffff" transform="translate({_number(placement.left)} {_number(placement.top)}) '
        f'scale({_number(placement.scale)})">\n'
        f"{shapes}\n"
        "  </g>\n"
        "</svg>\n"
    ).encode()


def build_assets() -> dict[Path, bytes]:
    """Every generated file and its contents."""
    full, small = read_mark(FULL_MARK), read_mark(SMALL_MARK)
    assets = {
        # Web: the browser tab, the iOS home screen and the web app manifest.
        STATIC_IMG / "favicon.ico": ico_bytes([favicon_tile(small, side) for side in FAVICON_SIZES]),
        STATIC_IMG / "favicon.svg": favicon_svg(small),
        STATIC_IMG / "apple-touch-icon.png": png_bytes(square_icon(full, APPLE_TOUCH_SIZE, TILE_MARK_WIDTH)),
        STATIC_IMG / "icon-192.png": png_bytes(square_icon(full, MANIFEST_SIZE, TILE_MARK_WIDTH)),
        STATIC_IMG / "icon-512.png": png_bytes(square_icon(full, LARGE_ICON_SIZE, TILE_MARK_WIDTH)),
        STATIC_IMG / "icon-maskable-512.png": png_bytes(square_icon(full, LARGE_ICON_SIZE, MASKABLE_MARK_WIDTH)),
        # Masters for a future phone app and the project's public profiles.
        GENERATED / "ios-app-icon-1024.png": png_bytes(square_icon(full, STORE_MASTER_SIZE, TILE_MARK_WIDTH)),
        GENERATED / "google-play-icon-512.png": png_bytes(square_icon(full, LARGE_ICON_SIZE, TILE_MARK_WIDTH)),
        GENERATED / "android-adaptive-foreground-432.png": png_bytes(draw(
            full, size=(ADAPTIVE_FOREGROUND_SIZE, ADAPTIVE_FOREGROUND_SIZE),
            placement=tile_placement(full, ADAPTIVE_FOREGROUND_SIZE, ADAPTIVE_MARK_WIDTH),
            color=WHITE, paint_background=no_background)),
        GENERATED / "avatar-1024.png": png_bytes(square_icon(full, STORE_MASTER_SIZE, TILE_MARK_WIDTH)),
    }
    for width in MARK_PNG_WIDTHS:
        assets[GENERATED / f"metalist-mark-black-{width}.png"] = png_bytes(mark_alone(full, width, BLACK))
        assets[GENERATED / f"metalist-mark-white-{width}.png"] = png_bytes(mark_alone(full, width, WHITE))
    return assets


def main() -> None:
    GENERATED.mkdir(exist_ok=True)
    for path, contents in build_assets().items():
        path.write_bytes(contents)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
