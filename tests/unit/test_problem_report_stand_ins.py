"""The stand-ins a problem report gives tag names (app/services/problem_report_redaction.py).

Found 2026-11-20 from a test that failed once in a full run: a drawn stand-in that came out as the
tag itself (`2026` drawn as `2026`), as another of the vault's tags, or the same as a sibling's,
stopped the report with an error instead of being drawn again. For a four-digit tag that is one
report in ten thousand; for a note tagged `5` it is one in ten, and with every digit a tag, every
report. A stand-in is now drawn until it is free, and made a character longer when its shape has
no free one left."""

from __future__ import annotations

import string

import pytest

from app.services.problem_report_redaction import SPEC, make_stand_ins

# Enough draws that a one-in-ten failure cannot pass by luck.
_DRAWS = 300
DIGITS = frozenset(string.digits)
LETTERS = frozenset(string.ascii_lowercase)


def _assert_sound(tags: frozenset[str], *, real_tags: frozenset[str]) -> dict[str, str]:
    by_tag = dict(make_stand_ins(tags, real_tags=real_tags).by_tag)
    assert set(by_tag) == set(tags)
    drawn = [by_tag[tag] for tag in tags if tag not in SPEC.meta_tags]
    assert len(set(drawn)) == len(drawn), f"two tags share a stand-in: {by_tag}"
    for stand_in in drawn:
        assert stand_in.casefold() not in real_tags, f"a stand-in is a real tag: {by_tag}"
        assert stand_in not in SPEC.meta_tags
        assert stand_in.isascii()
    return by_tag


def test_one_digit_tags_always_get_stand_ins() -> None:
    # Drawn blindly, a digit is itself one time in ten, and five of them clash more often than not.
    tags = frozenset({"1", "2", "3", "4", "5"})
    for _ in range(_DRAWS):
        _assert_sound(tags, real_tags=tags)


def test_a_tag_whose_shape_has_no_free_stand_in_gets_a_longer_one() -> None:
    # Every digit is a tag of the vault: no single digit can stand in for `7`.
    for _ in range(_DRAWS):
        by_tag = _assert_sound(frozenset({"7"}), real_tags=DIGITS)
        assert len(by_tag["7"]) > 1 and by_tag["7"][0].isdigit()


def test_a_stand_in_is_never_another_tag_of_the_vault() -> None:
    # The note's tag is `ab`; the vault also has every two-letter tag starting with a to y.
    real_tags = frozenset({first + second for first in LETTERS - {"z"} for second in LETTERS})
    for _ in range(_DRAWS):
        _assert_sound(frozenset({"ab"}), real_tags=real_tags)


def test_a_year_tag_never_stands_in_for_itself() -> None:
    # One draw in ten thousand gave `2026` for `2026`: checked by leaving only that draw free.
    all_but_one = frozenset(f"{number:04d}" for number in range(10_000)) - {"0000"}
    for _ in range(_DRAWS):
        by_tag = _assert_sound(frozenset({"2026"}), real_tags=all_but_one)
        assert by_tag["2026"] != "2026"


def test_folders_share_their_stand_in_segments_and_keep_their_slashes() -> None:
    tags = frozenset({"home/", "home/garden/", "home/garage/", "work/"})
    for _ in range(_DRAWS):
        by_tag = _assert_sound(tags, real_tags=frozenset(tag.casefold() for tag in tags))
        home = by_tag["home/"]
        assert home.endswith("/") and home.count("/") == 1
        assert by_tag["home/garden/"].startswith(home) and by_tag["home/garage/"].startswith(home)
        assert by_tag["home/garden/"] != by_tag["home/garage/"]
        assert not by_tag["work/"].startswith(home)
        # Siblings keep their alphabetical order (garage before garden, home before work).
        assert by_tag["home/garage/"] < by_tag["home/garden/"]
        assert home < by_tag["work/"]


def test_metalist_s_own_tags_stay_and_a_tag_keeps_its_at_sign() -> None:
    tags = frozenset({"@todo", "@custom", "custom"})
    for _ in range(_DRAWS):
        by_tag = _assert_sound(tags, real_tags=frozenset({"@custom", "custom"}))
        assert by_tag["@todo"] == "@todo"
        assert by_tag["@custom"] == "@" + by_tag["custom"]


@pytest.mark.parametrize("tag", ["--", "=", "a", "A", "é", "日本"])
def test_a_tag_of_any_shape_gets_a_stand_in_that_is_not_itself(tag: str) -> None:
    for _ in range(_DRAWS):
        by_tag = _assert_sound(frozenset({tag}), real_tags=frozenset({tag.casefold()}))
        assert by_tag[tag] != tag
