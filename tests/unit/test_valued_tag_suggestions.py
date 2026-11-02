"""A tag used with values, in the tag bar's suggestions (docs/design/tag-properties.md, "Last time's
values"; the maintainer, 2026-11-02): the last note's values, then the bare tag, and nothing else
for that tag. Each value had counted as a tag of its own, so the list read jogging=3, jogging=3,
jogging, jogging=2, jogging=5 and pushed the other tags down."""

from __future__ import annotations

from app.services.note_store import store
from app.services.tag_suggestions import suggest_tags_with_reasons_for_note
from tests.unit.test_super_tag_last_values import _note, live_database  # noqa: F401 (the fixture)

_LIMIT = 8


def _empty_bar(note_id: str) -> list[str]:
    """What the tag bar offers after the note's written tags, nothing typed yet."""
    written = store.get_note(note_id).tags.split()
    return [suggestion.tag for suggestion in suggest_tags_with_reasons_for_note(
        note_id=note_id, anchors=written, explicit_tags=written, prefix="",
        content_html=store.get_note(note_id).content, limit=_LIMIT,
    )]


def _typed(prefix: str, note_id: str) -> list[str]:
    written = store.get_note(note_id).tags.split()
    return [suggestion.tag for suggestion in suggest_tags_with_reasons_for_note(
        note_id=note_id, anchors=written, explicit_tags=[*written, prefix], prefix=prefix,
        content_html=store.get_note(note_id).content, limit=_LIMIT,
    )]


def _runs() -> None:
    # Made in this order: the last one is the newest.
    for index, tags in enumerate(["exercise jogging=3", "exercise jogging=5", "exercise jogging:miles=4",
                                  "exercise jogging=2 weights", "exercise jogging=3"]):
        _note(f"run{index}", tags=tags, parent_id=None)
    _note("today", tags="exercise", parent_id=None)


def _jogging_entries(shown: list[str]) -> list[str]:
    return [tag for tag in shown if tag.casefold().startswith("jogging")]


def test_the_last_values_then_the_bare_tag_then_the_other_tags(live_database) -> None:
    _runs()

    shown = _empty_bar("today")

    assert shown[:3] == ["jogging=3", "jogging", "weights"]
    assert _jogging_entries(shown) == ["jogging=3", "jogging"]


def test_the_last_values_as_the_newest_note_wrote_them(live_database) -> None:
    _runs()
    _note("run5", tags="exercise jogging:miles=6", parent_id=None)

    shown = _empty_bar("today")

    assert shown[:2] == ["jogging:miles=6", "jogging"]
    assert _jogging_entries(shown) == ["jogging:miles=6", "jogging"]


def test_typing_the_start_of_the_tag_offers_the_same_pair(live_database) -> None:
    _runs()

    assert _typed("jog", "today") == ["jogging=3", "jogging"]


def test_the_whole_name_typed_offers_only_the_values(live_database) -> None:
    _runs()

    assert _jogging_entries(_typed("jogging", "today")) == ["jogging=3"]


def test_a_tag_ranks_by_all_its_notes_whatever_their_values(live_database) -> None:
    # Six runs, each with its own distance, against two notes with weights: jogging goes with
    # exercise far more often, though no single value of it does.
    for index in range(6):
        _note(f"run{index}", tags=f"exercise jogging={index + 1}", parent_id=None)
    for index in range(2):
        _note(f"lift{index}", tags="exercise weights", parent_id=None)
    _note("today", tags="exercise", parent_id=None)

    shown = _empty_bar("today")

    assert shown[:3] == ["jogging=6", "jogging", "weights"]


def test_a_tag_never_given_values_is_offered_once(live_database) -> None:
    _runs()

    assert _empty_bar("today").count("weights") == 1
