"""A skin's CSS and art agree with each other (docs/ui/skins.md)."""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

STATIC_ROOT = Path("app/static")
SKIN_CSS_DIRECTORY = STATIC_ROOT / "css" / "skins"
SKIN_ART_DIRECTORY = STATIC_ROOT / "img" / "skins"
BASE_TEMPLATE = Path("app/templates/base.html")

SKIN_NAMES = sorted(path.stem for path in SKIN_CSS_DIRECTORY.glob("*.css"))
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
RULE_PRELUDE = re.compile(r"([^{};]+)\{")
ART_URL = re.compile(r'url\("/static/([^"]+)"\)')

# Browsers swap a larger custom cursor for the regular one near the window's edges.
MAX_CURSOR_CSS_PIXELS = 32
HIGH_DENSITY_SCALE = 2
PNG_SIZE_OFFSET = 16
PNG_SIZE_FORMAT = ">II"
PNG_SIZE_BYTES = 8


def _css_of(skin: str) -> str:
    return CSS_COMMENT.sub("", (SKIN_CSS_DIRECTORY / f"{skin}.css").read_text(encoding="utf-8"))


def _selectors_of(prelude: str) -> list[str]:
    """The selectors of a rule: its commas outside :is(...) and :not(...)."""
    selectors = [""]
    depth = 0
    for character in prelude:
        depth += (character == "(") - (character == ")")
        if character == "," and depth == 0:
            selectors.append("")
        else:
            selectors[-1] += character
    return [selector.strip() for selector in selectors]


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        image.seek(PNG_SIZE_OFFSET)
        return struct.unpack(PNG_SIZE_FORMAT, image.read(PNG_SIZE_BYTES))


def _pixel_limit_of(cursor: Path) -> int:
    if cursor.stem.endswith("@2x"):
        return MAX_CURSOR_CSS_PIXELS * HIGH_DENSITY_SCALE
    return MAX_CURSOR_CSS_PIXELS


def test_there_is_a_skin() -> None:
    assert SKIN_NAMES == ["illuminated"]


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_every_rule_is_scoped_to_its_skin(skin: str) -> None:
    """With another theme chosen the file does nothing, so its art is never downloaded."""
    scope = f'html[data-skin="{skin}"]'
    preludes = [match.strip() for match in RULE_PRELUDE.findall(_css_of(skin)) if not match.strip().startswith("@")]
    assert preludes
    unscoped = [selector for prelude in preludes for selector in _selectors_of(prelude) if not selector.startswith(scope)]
    assert unscoped == []


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_art_and_css_match(skin: str) -> None:
    used = {STATIC_ROOT / relative for relative in ART_URL.findall(_css_of(skin))}
    missing = sorted(str(path) for path in used if not path.is_file())
    assert missing == []
    art = {path for path in (SKIN_ART_DIRECTORY / skin).iterdir() if path.name != ".DS_Store"}
    # A cursor's 2x picture is named by the image-set beside its 1x.
    assert sorted(path.name for path in art - used) == []


# Fonts that exist on one system only: on the others a skin would silently look different.
SYSTEM_ONLY_FONTS = ("Apple Chancery", "Luminari", "Zapfino", "Papyrus", "Segoe Script")
FONT_FILE = re.compile(r'url\("/static/(fonts/[^"]+)"\)')


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_skin_ships_its_fonts(skin: str) -> None:
    css = _css_of(skin)
    assert [font for font in SYSTEM_ONLY_FONTS if font in css] == []
    files = FONT_FILE.findall(css)
    assert files
    for relative in files:
        assert (STATIC_ROOT / relative).is_file(), relative
        assert (STATIC_ROOT / relative).with_name("OFL.txt").is_file(), f"{relative} ships without its licence"


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_cursors_fit_the_browsers_limit(skin: str) -> None:
    cursors = sorted((SKIN_ART_DIRECTORY / skin).glob("cursor-*.png"))
    assert cursors
    for cursor in cursors:
        width, height = _png_size(cursor)
        assert max(width, height) <= _pixel_limit_of(cursor), cursor.name


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_skin_is_linked(skin: str) -> None:
    assert f"/static/css/skins/{skin}.css" in BASE_TEMPLATE.read_text(encoding="utf-8")
