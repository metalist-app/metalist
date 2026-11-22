"""Notes with Links (docs/ui/command-palette.md; agreed with the maintainer, 2026-11-21, their
notes: "filter by notes linked to", "filter by notes with broken links"): a tab kept to the
notes other notes link to, to the notes that contain a link, or to the notes with a link that
leads nowhere. They are kinds of the Notes with Files filter: one at a time, the same chip."""
from __future__ import annotations

import pytest

from app.services.backlink_index import BacklinkIndex
from app.services.file_kinds import (
    LINK_FILTER_BROKEN,
    LINK_FILTER_KINDS,
    LINK_FILTER_LINKED,
    LINK_FILTER_LINKS,
    is_file_filter_kind,
    is_link_filter_kind,
    make_file_filter,
)
from app.services.input_errors import InputRejected
from app.services.link_filters import notes_kept_by_link_filter

TRIP = "d0000000-0000-4000-8000-000000000001"
READING = "d0000000-0000-4000-8000-000000000002"
DIARY = "d0000000-0000-4000-8000-000000000003"
PLAIN = "d0000000-0000-4000-8000-000000000004"
PHOTO = "d0000000-0000-4000-8000-00000000000f"
GONE = "d0000000-0000-4000-8000-0000000000ff"
NOTES = frozenset({TRIP, READING, DIARY, PLAIN})
FILES = frozenset({PHOTO})
# Reading list links to Trip plan; Diary embeds a photo and links to a note that is gone;
# Trip plan links to itself only; Plain has no link.
CONTENTS = {
    TRIP: f"<div>Trip plan, see [[{TRIP}]]</div>",
    READING: f"<div>Reading list</div><div>[[{TRIP}|the trip]]</div>",
    DIARY: f"<div>Diary ![[{PHOTO}]] and [[{GONE}]]</div>",
    PLAIN: "<div>Plain [[not a link]] [[search:@todo]]</div>",
}


def _kept(kind: str) -> set[str]:
    index = BacklinkIndex()
    for note_id, content in CONTENTS.items():
        index.upsert(note_id, content, "")
    return notes_kept_by_link_filter(kind, targets_by_note=index.targets_by_note(), note_ids=NOTES, file_ids=FILES)


def test_linked_keeps_the_notes_another_note_links_to() -> None:
    # A note's link to itself is no link from another note.
    assert _kept(LINK_FILTER_LINKED) == {TRIP}


def test_links_keeps_the_notes_that_link_to_a_note() -> None:
    # A file is no note (Notes with Files finds those), and a link to a note that is gone is broken.
    assert _kept(LINK_FILTER_LINKS) == {READING}


def test_broken_keeps_the_notes_with_a_link_that_leads_nowhere() -> None:
    assert _kept(LINK_FILTER_BROKEN) == {DIARY}


def test_a_note_that_is_gone_is_kept_by_none() -> None:
    index = BacklinkIndex()
    index.upsert(GONE, f"<div>[[{TRIP}]] [[{PHOTO}]]</div>", "")
    index.upsert(READING, CONTENTS[READING], "")
    for kind, kept in [(LINK_FILTER_LINKS, {READING}), (LINK_FILTER_LINKED, {TRIP}), (LINK_FILTER_BROKEN, set())]:
        assert notes_kept_by_link_filter(kind, targets_by_note=index.targets_by_note(), note_ids=NOTES, file_ids=FILES) == kept


def test_the_link_kinds_are_kinds_of_the_files_filter() -> None:
    assert LINK_FILTER_KINDS == (LINK_FILTER_LINKS, LINK_FILTER_LINKED, LINK_FILTER_BROKEN)
    for kind in LINK_FILTER_KINDS:
        assert is_file_filter_kind(kind) and is_link_filter_kind(kind) and make_file_filter(kind) == kind
    assert not is_link_filter_kind("image") and not is_link_filter_kind("any")
    with pytest.raises(InputRejected):
        make_file_filter("linkz")


def test_another_kind_is_refused() -> None:
    with pytest.raises(AssertionError):
        notes_kept_by_link_filter("image", targets_by_note={}, note_ids=NOTES, file_ids=FILES)
