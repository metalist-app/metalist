"""MetaList's icons are generated from the mark's sources in brand/ (brand/README.md)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_brand_icons as brand  # noqa: E402


def _pixels(image: Image.Image) -> tuple[tuple[int, int], str, bytes]:
    return image.size, image.mode, image.tobytes()


def _ico_frames(contents: bytes) -> dict[tuple[int, int], tuple[tuple[int, int], str, bytes]]:
    image = Image.open(io.BytesIO(contents))
    frames = {}
    for size in sorted(image.info["sizes"]):
        image.size = size
        frames[size] = _pixels(image.copy().convert("RGBA"))
    return frames


def test_each_committed_icon_is_what_the_script_draws() -> None:
    # A change to brand/ needs `.venv/bin/python scripts/generate_brand_icons.py` and the
    # regenerated files committed with it.
    for path, drawn in brand.build_assets().items():
        committed = path.read_bytes()
        if path.suffix == ".svg":
            assert committed == drawn, path
        elif path.suffix == ".ico":
            assert _ico_frames(committed) == _ico_frames(drawn), path
        else:
            # Pixels, not bytes: the PNG encoder may compress differently on another platform.
            assert _pixels(Image.open(io.BytesIO(committed))) == _pixels(Image.open(io.BytesIO(drawn))), path


def test_the_favicon_holds_the_three_tab_sizes() -> None:
    assert sorted(Image.open(brand.STATIC_IMG / "favicon.ico").info["sizes"]) == [(16, 16), (32, 32), (48, 48)]


@pytest.mark.parametrize("name", ["apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"])
def test_home_screen_icons_have_no_transparency(name: str) -> None:
    # iOS shows transparency as black and app stores refuse an alpha channel.
    assert Image.open(brand.STATIC_IMG / name).mode == "RGB"


def test_the_manifest_lists_icons_that_exist_at_their_sizes() -> None:
    manifest = json.loads((ROOT / "app/static/manifest.json").read_text())
    # Added to a phone's home screen, MetaList opens full screen with its own icon; desktop
    # Chrome may offer to install it too (the maintainer, 2026-10-24, docs/ui/phone.md).
    assert manifest["display"] == "standalone"
    for icon in manifest["icons"]:
        path = ROOT / "app" / icon["src"].removeprefix("/")
        width, height = (int(side) for side in icon["sizes"].split("x"))
        assert Image.open(path).size == (width, height)


@pytest.mark.parametrize("template", ["base.html", "locked.html", "namespace_deleted.html", "namespace_renamed.html"])
def test_every_page_links_the_icons(template: str) -> None:
    source = (ROOT / "app/templates" / template).read_text()
    for link in ('rel="icon" type="image/x-icon"', 'rel="icon" type="image/svg+xml" href="/static/img/favicon.svg',
                 'rel="apple-touch-icon" href="/static/img/apple-touch-icon.png', 'rel="manifest" href="/static/manifest.json'):
        assert link in source
