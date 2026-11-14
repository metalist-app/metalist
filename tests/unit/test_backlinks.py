from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pytest

from app.services.backlink_index import BacklinkIndex

import app.services.backlinks as backlinks
import app.services.backlink_index as backlink_index_module


@dataclass(frozen=True)
class _Note:
    id: str
    parent_id: Optional[str]
    content: str
    tags: str = ""
    updated_at: Optional[datetime] = None


class _FakeStore:
    def __init__(self, *, notes: Dict[str, _Note], children_by_parent: Dict[Optional[str], List[str]]):
        self._notes = notes
        self._backlink_index = BacklinkIndex()
        for note in notes.values():
            self._backlink_index.upsert(note.id, note.content, note.tags)
        self._children_by_parent = children_by_parent

    def has_backlinks(self, note_id: str) -> bool:
        return self._backlink_index.has_backlinks(note_id)

    def get_backlink_counts(self, note_id: str) -> dict[str, int]:
        return self._backlink_index.get_counts(note_id)

    def has_note(self, note_id: str) -> bool:
        return note_id in self._notes

    def get_note(self, note_id: str) -> _Note:
        return self._notes[note_id]

    def get_children(self, parent_id: Optional[str]) -> List[str]:
        return list(self._children_by_parent.get(parent_id, []))


def test_list_backlinks_for_note_finds_embed_and_link_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    target_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    notes = {
        "root-a": _Note("root-a", None, f"<div>![[{target_id}]]</div>"),
        "root-b": _Note("root-b", None, "<div>no refs</div>"),
        "child-b1": _Note("child-b1", "root-b", f"<div>[[{target_id}]]</div>"),
        target_id: _Note(target_id, None, "<div>target</div>"),
    }
    fake_store = _FakeStore(
        notes=notes,
        children_by_parent={
            None: ["root-a", "root-b", target_id],
            "root-b": ["child-b1"],
        },
    )
    monkeypatch.setattr(backlinks, "note_store", fake_store)

    rows = backlinks.list_backlinks_for_note(target_id, None)

    assert [row["id"] for row in rows] == ["root-a", "child-b1"]


def test_cached_backlinks_never_edited_keep_current_tree_order_and_only_read_referrers(monkeypatch):
    target_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    notes = {
        "a": _Note("a", None, f"First [[{target_id}]]"),
        "b": _Note("b", None, f"Second ![[{target_id}]]"),
        target_id: _Note(target_id, None, "Source"),
    }
    children = {None: ["a", "b", target_id]}
    store = _FakeStore(notes=notes, children_by_parent=children)
    read_ids = []

    def unexpected_parse(*args):
        pytest.fail("Backlink queries must use cached reference membership")

    def read_referrer(note_id):
        assert note_id != target_id
        read_ids.append(note_id)
        return notes[note_id]

    monkeypatch.setattr(backlink_index_module, "collect_active_reference_tokens", unexpected_parse)
    monkeypatch.setattr(store, "get_note", read_referrer)
    monkeypatch.setattr(backlinks, "note_store", store)
    assert [row["id"] for row in backlinks.list_backlinks_for_note(target_id, None)] == ["a", "b"]
    children[None] = [target_id, "b", "a"]
    assert [row["id"] for row in backlinks.list_backlinks_for_note(target_id, None)] == ["b", "a"]
    assert read_ids == ["a", "b", "b", "a"]


def test_list_backlinks_for_note_strips_reference_tokens_from_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    target_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    notes = {
        "ref-note": _Note("ref-note", None, f"<div>blah ![[{target_id}]] more</div>"),
        target_id: _Note(target_id, None, "<div>target</div>"),
    }
    fake_store = _FakeStore(
        notes=notes,
        children_by_parent={None: ["ref-note", target_id]},
    )
    monkeypatch.setattr(backlinks, "note_store", fake_store)

    rows = backlinks.list_backlinks_for_note(target_id, None)

    assert len(rows) == 1
    assert rows[0]["id"] == "ref-note"
    assert rows[0]["preview"] == "blah more"
    assert target_id not in rows[0]["preview"]


def test_list_backlinks_for_note_raises_for_missing_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_store = _FakeStore(notes={}, children_by_parent={None: []})
    monkeypatch.setattr(backlinks, "note_store", fake_store)

    with pytest.raises(KeyError):
        backlinks.list_backlinks_for_note("does-not-exist", None)


def test_list_backlinks_for_note_returns_multiple_rows_for_multiple_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    notes = {
        "source": _Note("source", None, f"<div>[[{target_id}]] and ![[{target_id}]]</div>"),
        target_id: _Note(target_id, None, "<div>target</div>"),
    }
    fake_store = _FakeStore(
        notes=notes,
        children_by_parent={None: ["source", target_id]},
    )
    monkeypatch.setattr(backlinks, "note_store", fake_store)

    rows = backlinks.list_backlinks_for_note(target_id, None)

    assert len(rows) == 2
    assert rows[0]["id"] == "source"
    assert rows[1]["id"] == "source"


def test_list_backlinks_for_note_can_scope_sources_to_search_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    notes = {
        "source-in": _Note("source-in", None, f"<div>[[{target_id}]]</div>"),
        "source-out": _Note("source-out", None, f"<div>[[{target_id}]]</div>"),
        target_id: _Note(target_id, None, "<div>target</div>"),
    }
    fake_store = _FakeStore(
        notes=notes,
        children_by_parent={None: ["source-in", "source-out", target_id]},
    )
    monkeypatch.setattr(backlinks, "note_store", fake_store)

    rows = backlinks.list_backlinks_for_note(
        target_id,
        source_note_ids={"source-in", target_id},
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "source-in"


def test_note_id_links_count_even_in_notes_with_square_formatting_wrappers(monkeypatch):
    # A [[...]] holding exactly a note id is always a link (docs/ui/references.md).
    target_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    notes = {
        "scoped": _Note("scoped", None, f"[[{target_id}]]", "[[@red]]"),
        "embedded": _Note("embedded", None, f"![[{target_id}]]", "[[@red]]"),
        target_id: _Note(target_id, None, "Source"),
    }
    monkeypatch.setattr(backlinks, "note_store", _FakeStore(
        notes=notes, children_by_parent={None: list(notes)},
    ))
    assert [row["id"] for row in backlinks.list_backlinks_for_note(target_id, None)] == ["scoped", "embedded"]


def test_backlinks_list_the_most_recently_edited_note_first(monkeypatch):
    # The Backlinks page shows them in this order (docs/ready-to-build/reference-cards.md §3).
    target_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    def edited(day: int) -> datetime:
        return datetime(2026, 11, day, tzinfo=timezone.utc)
    notes = {
        "old": _Note("old", None, f"[[{target_id}]]", updated_at=edited(1)),
        "never": _Note("never", None, f"[[{target_id}]]"),
        "new": _Note("new", None, f"[[{target_id}]] [[{target_id}]]", updated_at=edited(9)),
        "middle-a": _Note("middle-a", None, f"[[{target_id}]]", updated_at=edited(5)),
        "middle-b": _Note("middle-b", None, f"[[{target_id}]]", updated_at=edited(5)),
        target_id: _Note(target_id, None, "Source"),
    }
    store = _FakeStore(notes=notes, children_by_parent={None: ["old", "never", "middle-b", "new", "middle-a", target_id]})
    monkeypatch.setattr(backlinks, "note_store", store)

    rows = backlinks.list_backlinks_for_note(target_id, None)

    # Edited at the same time: in the tree's order. Never edited: last.
    assert [row["id"] for row in rows] == ["new", "new", "middle-b", "middle-a", "old", "never"]
