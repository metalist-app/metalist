"""The File size order (app/services/root_sorting.py): how roots rank under each Files filter, and
the sizes the browser shows beside them (docs/ui/command-palette.md, Sort Order)."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

import pytest

import app.services.root_sorting as root_sorting
import app.services.snapshot as snapshot
from app.services.file_registry import FileDetails, FileRegistry
from tests.unit.test_file_filter import _FakeNoteStore, _note

ZIP_ID = "11111111-bbbb-4bbb-8bbb-111111111111"
TINY_PICTURE_ID = "22222222-bbbb-4bbb-8bbb-222222222222"
BIG_PICTURE_ID = "33333333-bbbb-4bbb-8bbb-333333333333"
TRIP_PDF_ID = "44444444-bbbb-4bbb-8bbb-444444444444"
TRIP_CHILD_PDF_ID = "55555555-bbbb-4bbb-8bbb-555555555555"
USED_TWICE_PDF_ID = "66666666-bbbb-4bbb-8bbb-666666666666"
TIED_PDF_ID = "77777777-bbbb-4bbb-8bbb-777777777777"
OTHER_TIED_PDF_ID = "88888888-bbbb-4bbb-8bbb-888888888888"

ZIP_BYTES = 900
TINY_PICTURE_BYTES = 1
BIG_PICTURE_BYTES = 300
TRIP_PDF_BYTES = 100
TRIP_CHILD_PDF_BYTES = 150
USED_TWICE_PDF_BYTES = 200
TIED_PDF_BYTES = 5

_DETAILS = {
    ZIP_ID: FileDetails(title="huge.zip", thumbnail_kind="archive", size_bytes=ZIP_BYTES),
    TINY_PICTURE_ID: FileDetails(title="tiny.png", thumbnail_kind="image", size_bytes=TINY_PICTURE_BYTES),
    BIG_PICTURE_ID: FileDetails(title="big.png", thumbnail_kind="image", size_bytes=BIG_PICTURE_BYTES),
    TRIP_PDF_ID: FileDetails(title="trip.pdf", thumbnail_kind="pdf", size_bytes=TRIP_PDF_BYTES),
    TRIP_CHILD_PDF_ID: FileDetails(title="trip-child.pdf", thumbnail_kind="pdf", size_bytes=TRIP_CHILD_PDF_BYTES),
    USED_TWICE_PDF_ID: FileDetails(title="twice.pdf", thumbnail_kind="pdf", size_bytes=USED_TWICE_PDF_BYTES),
    TIED_PDF_ID: FileDetails(title="tied.pdf", thumbnail_kind="pdf", size_bytes=TIED_PDF_BYTES),
    OTHER_TIED_PDF_ID: FileDetails(title="other-tied.pdf", thumbnail_kind="pdf", size_bytes=TIED_PDF_BYTES),
}

ROOTS = ["plain", "tied-first", "tied-second", "used-twice", "trip", "zip-and-tiny", "big-picture"]
BY_TOTAL = ["zip-and-tiny", "big-picture", "trip", "used-twice", "tied-first", "tied-second", "plain"]


def _registry() -> FileRegistry:
    registry = FileRegistry()
    registry.replace_all_with_thumbnail_kinds({file_id: details.thumbnail_kind for file_id, details in _DETAILS.items()})
    registry.install_details_loader(lambda: _DETAILS)
    return registry


@pytest.fixture
def notes_with_sized_files(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {note_id: _note(note_id, None) for note_id in ROOTS}
    notes["trip-child"] = _note("trip-child", "trip")
    notes["used-twice-child"] = _note("used-twice-child", "used-twice")
    references: Dict[str, Set[str]] = {
        "zip-and-tiny": {ZIP_ID, TINY_PICTURE_ID},
        "big-picture": {BIG_PICTURE_ID},
        "trip": {TRIP_PDF_ID},
        "trip-child": {TRIP_CHILD_PDF_ID},
        "used-twice": {USED_TWICE_PDF_ID},
        "used-twice-child": {USED_TWICE_PDF_ID},
        "tied-first": {TIED_PDF_ID},
        "tied-second": {OTHER_TIED_PDF_ID},
    }
    store = _FakeNoteStore(
        notes=notes,
        children_by_parent={None: ROOTS, "trip": ["trip-child"], "used-twice": ["used-twice-child"]},
        references=references,
        inline_image_note_ids=set(),
    )
    registry = _registry()
    monkeypatch.setattr(root_sorting, "note_store", store)
    monkeypatch.setattr(root_sorting, "file_registry", registry)
    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "file_registry", registry)
    monkeypatch.setattr(snapshot, "get_all_locks", lambda: {})


def _ordered(sort_mode: str, file_filter: Optional[str]) -> List[str]:
    return root_sorting.get_root_ids_for_sort_mode(sort_mode, root_timestamps={}, file_filter=file_filter)


def test_the_biggest_total_comes_first_with_children_counted_and_a_reused_file_counted_once(notes_with_sized_files) -> None:
    assert _ordered("file-size", "any") == BY_TOTAL


def test_reversed_the_smallest_total_comes_first(notes_with_sized_files) -> None:
    assert _ordered("file-size-reversed", "any") == BY_TOTAL[::-1]


def test_equal_totals_keep_the_manual_order(notes_with_sized_files) -> None:
    ordered = _ordered("file-size", "any")
    assert ordered.index("tied-first") < ordered.index("tied-second")


def test_only_the_files_the_filter_keeps_count(notes_with_sized_files) -> None:
    ordered = _ordered("file-size", "image")
    assert ordered[:2] == ["big-picture", "zip-and-tiny"]


def test_without_a_filter_every_file_counts(notes_with_sized_files) -> None:
    assert _ordered("file-size", None) == BY_TOTAL


def test_the_labels_give_each_listed_root_its_total_and_each_counted_file_its_size(notes_with_sized_files) -> None:
    assert root_sorting.build_file_size_labels(["trip", "used-twice", "plain"], "file-size", file_filter="any") == {
        "rootTotals": {"trip": TRIP_PDF_BYTES + TRIP_CHILD_PDF_BYTES, "used-twice": USED_TWICE_PDF_BYTES},
        "files": {
            TRIP_PDF_ID: TRIP_PDF_BYTES,
            TRIP_CHILD_PDF_ID: TRIP_CHILD_PDF_BYTES,
            USED_TWICE_PDF_ID: USED_TWICE_PDF_BYTES,
        },
    }


def test_the_labels_leave_out_files_the_filter_does_not_count(notes_with_sized_files) -> None:
    assert root_sorting.build_file_size_labels(["zip-and-tiny"], "file-size-reversed", file_filter="image") == {
        "rootTotals": {"zip-and-tiny": TINY_PICTURE_BYTES},
        "files": {TINY_PICTURE_ID: TINY_PICTURE_BYTES},
    }


@pytest.mark.parametrize("sort_mode", ["normal", "created", "updated", "alphabetical", "content-volume", "content-volume-reversed"])
def test_no_other_order_has_labels(notes_with_sized_files, sort_mode: str) -> None:
    assert root_sorting.build_file_size_labels(["trip"], sort_mode, file_filter="any") == {"rootTotals": {}, "files": {}}


def test_the_view_lists_the_order_and_carries_the_labels_of_what_it_lists(notes_with_sized_files) -> None:
    state = snapshot.build_view_state(
        editing_note_id=None, find_reveal_note_id=None, search=None, sort_mode="file-size",
        date_filter=None, file_filter="image", client_known_note_ids=set(), previous_root_ids=[],
        visible_top_root_id=None, visible_bottom_root_id=None, is_untagged_view=False, start_at_list_end=False,
    )
    assert state.children_by_parent[None] == ["big-picture", "zip-and-tiny"]
    assert state.metadata["fileSizes"] == {
        "rootTotals": {"big-picture": BIG_PICTURE_BYTES, "zip-and-tiny": TINY_PICTURE_BYTES},
        "files": {BIG_PICTURE_ID: BIG_PICTURE_BYTES, TINY_PICTURE_ID: TINY_PICTURE_BYTES},
    }


def test_the_registry_reads_sizes_once_and_keeps_them_current() -> None:
    registry = _registry()
    assert registry.sizes_of_kind("pdf")[TRIP_PDF_ID] == TRIP_PDF_BYTES

    registry.set_size(TRIP_PDF_ID, size_bytes=TRIP_PDF_BYTES + 1)
    assert registry.sizes_of_kind("pdf")[TRIP_PDF_ID] == TRIP_PDF_BYTES + 1

    added_id = "99999999-bbbb-4bbb-8bbb-999999999999"
    registry.add_with_thumbnail_kind(added_id, thumbnail_kind="pdf", title="later.pdf", size_bytes=TIED_PDF_BYTES)
    assert registry.sizes_of_kind("pdf")[added_id] == TIED_PDF_BYTES

    registry.remove_many({added_id})
    assert added_id not in registry.sizes_of_kind("any")


def test_a_size_changed_before_the_details_are_read_comes_from_them() -> None:
    registry = _registry()
    registry.set_size(TRIP_PDF_ID, size_bytes=TRIP_PDF_BYTES + 1)
    assert registry.sizes_of_kind("pdf")[TRIP_PDF_ID] == TRIP_PDF_BYTES
