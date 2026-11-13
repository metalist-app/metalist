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


def test_the_skins() -> None:
    assert SKIN_NAMES == ["fathom", "illuminated", "phosphor", "vellum"]


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
    # A skin of colours and fonts alone (Fathom) has no art.
    art_directory = SKIN_ART_DIRECTORY / skin
    art: set[Path] = set()
    if art_directory.is_dir():
        art = {path for path in art_directory.iterdir() if path.name != ".DS_Store"}
    # A cursor's 2x picture is named by the image-set beside its 1x.
    assert sorted(path.name for path in art - used) == []


# Fonts that exist on one system only: on the others a skin would silently look different.
SYSTEM_ONLY_FONTS = ("Apple Chancery", "Luminari", "Zapfino", "Papyrus", "Segoe Script")
FONT_FILE = re.compile(r'url\("/static/(fonts/[^"]+)"\)')


# Fathom writes in each system's own monospace, as the editor it follows does (the maintainer,
# 2026-11-11), and Phosphor as a terminal does (2026-11-12): skins that ship no font, ending on
# the generic family every system has.
SYSTEM_MONOSPACE_SKINS = ("fathom", "phosphor")
SHIPPED_FONT_SKINS = [skin for skin in SKIN_NAMES if skin not in SYSTEM_MONOSPACE_SKINS]
# Skins with cursors of their own; Fathom keeps the system's.
CURSOR_SKINS = ["illuminated"]


@pytest.mark.parametrize("skin", SYSTEM_MONOSPACE_SKINS)
def test_a_system_monospace_skin_falls_back_on_every_system(skin: str) -> None:
    css = _css_of(skin)
    assert FONT_FILE.findall(css) == []
    assert re.search(r"ui-monospace, Menlo, Consolas, \"DejaVu Sans Mono\", monospace;", css)


@pytest.mark.parametrize("skin", SHIPPED_FONT_SKINS)
def test_skin_ships_its_fonts(skin: str) -> None:
    css = _css_of(skin)
    assert [font for font in SYSTEM_ONLY_FONTS if font in css] == []
    files = FONT_FILE.findall(css)
    assert files
    for relative in files:
        assert (STATIC_ROOT / relative).is_file(), relative
        assert (STATIC_ROOT / relative).with_name("OFL.txt").is_file(), f"{relative} ships without its licence"


def test_the_skins_with_cursors() -> None:
    assert [skin for skin in SKIN_NAMES if any((SKIN_ART_DIRECTORY / skin).glob("cursor-*.png"))] == CURSOR_SKINS


@pytest.mark.parametrize("skin", CURSOR_SKINS)
def test_cursors_fit_the_browsers_limit(skin: str) -> None:
    # Real cursors only: the quill and hand are drawn on the page (skin-pointer.js).
    cursors = sorted((SKIN_ART_DIRECTORY / skin).glob("cursor-*.png"))
    assert cursors
    for cursor in cursors:
        width, height = _png_size(cursor)
        assert max(width, height) <= _pixel_limit_of(cursor), cursor.name


@pytest.mark.parametrize("skin", SKIN_NAMES)
def test_skin_is_linked(skin: str) -> None:
    assert f"/static/v/${{asset_version}}/css/skins/{skin}.css" in BASE_TEMPLATE.read_text(encoding="utf-8")


# Every text colour reads at 4.5 to 1 or better on the background it sits on (WCAG AA; the
# maintainer, 2026-11-12, docs/ready-to-build/phosphor-and-vellum-skins.md). Each pair names a
# text colour and a background from the skin's palette, or a meta colour (.meta-red) by its rule.
MIN_TEXT_CONTRAST = 4.5
CONTRAST_PAIRS = {
    "phosphor": [
        ("ink", "screen"), ("ink", "glass"), ("ink", "line"), ("bright", "screen"), ("bright", "line"),
        ("dim", "screen"), ("dim", "glass"), ("dim", "line"), ("faint", "screen"), ("faint", "glass"),
        ("red", "screen"), ("green", "screen"), ("blue", "screen"), ("amber", "screen"),
        (".meta-red", "screen"), (".meta-green", "screen"), (".meta-blue", "screen"),
        (".meta-red", "line"), (".meta-green", "line"), (".meta-blue", "line"),
    ],
    "vellum": [
        ("ink", "page"), ("ink", "sheet"), ("ink", "desk"), ("muted", "page"), ("muted", "desk"),
        ("muted", "sheet"), ("subtle", "page"), ("subtle", "desk"), ("link", "page"), ("link", "sheet"),
        ("tag", "page"), ("tag", "sheet"), ("accent", "page"), ("accent", "desk"),
        ("red", "page"), ("green", "page"), ("blue", "page"),
        (".meta-red", "page"), (".meta-green", "page"), (".meta-blue", "page"),
        (".meta-red", "sheet"), (".meta-green", "sheet"), (".meta-blue", "sheet"),
    ],
}
HEX_COLOUR = re.compile(r"#([0-9a-fA-F]{6})\b")
SRGB_LINEAR_LIMIT = 0.03928
SRGB_LINEAR_DIVISOR = 12.92
SRGB_GAMMA_OFFSET = 0.055
SRGB_GAMMA_SCALE = 1.055
SRGB_GAMMA = 2.4
LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)
CONTRAST_FLARE = 0.05
CHANNEL_MAX = 255
HEX_CHANNEL_WIDTH = 2


def _palette_colour(css: str, skin: str, name: str) -> str:
    if name.startswith("."):
        rule = re.search(rf'html\[data-skin="{skin}"\] {re.escape(name)} \{{\s*color: (#[0-9a-fA-F]{{6}});', css)
    else:
        rule = re.search(rf"--{skin}-{name}: (#[0-9a-fA-F]{{6}});", css)
    assert rule, f"{skin}: no colour {name}"
    return rule.group(1)


def _luminance(colour: str) -> float:
    digits = HEX_COLOUR.fullmatch(colour).group(1)
    channels = []
    for start in range(0, len(digits), HEX_CHANNEL_WIDTH):
        value = int(digits[start:start + HEX_CHANNEL_WIDTH], 16) / CHANNEL_MAX
        if value <= SRGB_LINEAR_LIMIT:
            channels.append(value / SRGB_LINEAR_DIVISOR)
        else:
            channels.append(((value + SRGB_GAMMA_OFFSET) / SRGB_GAMMA_SCALE) ** SRGB_GAMMA)
    return sum(weight * channel for weight, channel in zip(LUMINANCE_WEIGHTS, channels))


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + CONTRAST_FLARE) / (darker + CONTRAST_FLARE)


@pytest.mark.parametrize("skin", sorted(CONTRAST_PAIRS))
def test_every_text_colour_reads_on_its_background(skin: str) -> None:
    css = _css_of(skin)
    too_faint = []
    for text, background in CONTRAST_PAIRS[skin]:
        ratio = _contrast(_palette_colour(css, skin, text), _palette_colour(css, skin, background))
        if ratio < MIN_TEXT_CONTRAST:
            too_faint.append(f"{text} on {background}: {ratio:.2f}")
    assert too_faint == []
