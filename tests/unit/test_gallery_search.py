"""Under a search, a gallery's own meta tags don't narrow its pictures: `test @gallery` finds the
gallery by `@gallery`, and its pictures are the notes under it that `test` finds (the maintainer,
2026-11-11: meta tags pass to no child, so the gallery showed nothing)."""
from __future__ import annotations

import pytest

from app.services.snapshot import search_for_gallery_pictures


@pytest.mark.parametrize(
    ("search", "gallery_tags", "pictures_search"),
    [
        ("test @gallery", "test @gallery", "test"),
        ("test cats @gallery", "test @gallery", "test cats"),
        ("test @Gallery", "test @gallery=image", "test"),
        ("test @gallery OR dogs", "@gallery", "test OR dogs"),
        ("test @red", "test @gallery", "test @red"),
        ("@gallery", "@gallery", ""),
        ("test", "test @gallery", "test"),
        ('test "@gallery"', "@gallery", 'test "@gallery"'),
    ],
)
def test_the_galleries_own_meta_tags_leave_the_search(search: str, gallery_tags: str, pictures_search: str) -> None:
    assert " ".join(search_for_gallery_pictures(search, gallery_tags).split()) == pictures_search
