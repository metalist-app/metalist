from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3
from typing import Dict, List, Optional

import pytest

import app.services.snapshot as snapshot_module
from app.services.backlink_index import BacklinkIndex

from app.db.link_titles_sql import insert_link_title_row
from app.db.schema import initialize_schema
from app.services.link_titles import link_title_store
from app.services.snapshot import build_view_state
from tests.unit.snapshot_note_fixture import SnapshotTestNote as _Note


@pytest.fixture(autouse=True)
def _backlinks_button_on(monkeypatch):
    """The backlinks button is off for now (snapshot.SHOWS_BACKLINKS_BUTTON); these
    tests keep checking how it renders for when it returns."""
    monkeypatch.setattr(snapshot_module, "SHOWS_BACKLINKS_BUTTON", True)


class _FakeNoteStore:
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

    def get_inherited_non_meta_tag_terms(self, note_id: str) -> frozenset[str]:
        assert note_id in self._notes
        return frozenset()


HOST_ID = "11111111-1111-1111-1111-111111111111"
TARGET_ID = "22222222-2222-2222-2222-222222222222"
CHILD_ID = "33333333-3333-3333-3333-333333333333"
OTHER_ID = "44444444-4444-4444-4444-444444444444"
MISSING_ID = "99999999-9999-9999-9999-999999999999"


def _bootstrap_cached_link_title(*, url: str, title: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    initialize_schema(connection)
    now = datetime.now(timezone.utc)
    insert_link_title_row(
        connection,
        url=url,
        url_encryption_nonce=None,
        url_encryption_tag=None,
        title=title,
        title_encryption_nonce=None,
        title_encryption_tag=None,
        status="ok",
        last_error_kind=None,
        last_checked_at=now,
        last_success_at=now,
        last_failure_at=None,
        next_check_after=None,
        failure_count=0,
        created_at=now,
        updated_at=now,
    )
    link_title_store.bootstrap(connection=connection)
    return connection


def test_snapshot_finds_offscreen_backlinks_without_reading_offscreen_notes(monkeypatch):
    ids = [f"{index:08x}-1111-4111-8111-111111111111" for index in range(1000)]
    notes = {note_id: _Note(note_id, None, None, None, True, "Ordinary note", "")
             for note_id in ids}
    notes[ids[-1]].content = f"![[{ids[0]}]]"
    store = _FakeNoteStore(notes=notes, children_by_parent={None: ids})
    read_ids = set()
    original = store.get_note

    def track_read(note_id):
        read_ids.add(note_id)
        return original(note_id)

    monkeypatch.setattr(store, "get_note", track_read)
    monkeypatch.setattr(snapshot_module, "note_store", store)
    monkeypatch.setattr(snapshot_module, "get_all_locks", lambda: {})
    state = build_view_state(
        editing_note_id=None, find_reveal_note_id=None, search=None, sort_mode="normal", date_filter=None, file_filter=None,
        client_known_note_ids=set(), previous_root_ids=[], visible_top_root_id=None,
        visible_bottom_root_id=None, is_untagged_view=False,
        start_at_list_end=False,
    )
    first_window = snapshot_module.ROOT_BAND_MARGIN + 1
    assert len(state.payloads) == first_window
    assert "note-backlinks-link" in state.payloads[ids[0]]["content"]
    assert read_ids == set(ids[:first_window])


def _state_for(
    *,
    monkeypatch: pytest.MonkeyPatch,
    notes: Dict[str, _Note],
    children_by_parent: Dict[Optional[str], List[str]],
    **kwargs: object,
):
    editing_note_id = None
    if "editing_note_id" in kwargs:
        editing_note_id = kwargs["editing_note_id"]
    if editing_note_id is not None and not isinstance(editing_note_id, str):
        raise TypeError("editing_note_id must be a string or None")
    store = _FakeNoteStore(notes=notes, children_by_parent=children_by_parent)

    import app.services.snapshot as snapshot

    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "get_all_locks", lambda: {})
    return build_view_state(
        editing_note_id=editing_note_id, find_reveal_note_id=None,
        search=None,
        sort_mode="normal", date_filter=None, file_filter=None,
        client_known_note_ids=set(), previous_root_ids=[],
        visible_top_root_id=None,
        visible_bottom_root_id=None,
        is_untagged_view=False,
        start_at_list_end=False,
    )


def test_view_state_renders_note_with_bare_at_tag_without_blocking_other_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, "<div>First note</div>", "@"),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>Second note</div>", ""),
    }

    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID]},
    )

    assert "First note" in state.payloads[HOST_ID]["content"]
    assert state.payloads[HOST_ID]["tags"] == "@"
    assert "Second note" in state.payloads[TARGET_ID]["content"]


def test_embed_reference_renders_as_block_and_includes_descendants(monkeypatch: pytest.MonkeyPatch) -> None:
    # A note whose only content is the reference embeds it.
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>embedded root</div>", ""),
        CHILD_ID: _Note(
            CHILD_ID,
            TARGET_ID,
            None,
            None,
            False,
            "<div>embedded child</div><div>embedded child hidden line</div>",
            "",
        ),
        OTHER_ID: _Note(OTHER_ID, CHILD_ID, None, None, False, "<div>embedded grandchild</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={
            None: [HOST_ID, TARGET_ID],
            TARGET_ID: [CHILD_ID],
            CHILD_ID: [OTHER_ID],
        },
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert state.payloads[HOST_ID]["flags"]["isCollapsible"] is True
    assert "note-embed-block" in rendered
    assert "note-reference-toggle" not in rendered
    assert f'data-embed-ref-id="{TARGET_ID}"' in rendered
    assert f'data-embed-note-id="{TARGET_ID}"' in rendered
    assert "embedded root" in rendered
    assert "embedded child" in rendered
    assert "embedded child hidden line" in rendered
    assert "embedded grandchild" in rendered
    assert 'class="note-reference-link note-source-arrow"' in rendered
    assert "note-embed-source-link" not in rendered
    assert 'title="Go to source note" aria-label="Go to source note"' in rendered
    assert "note-reference-link-kind" not in rendered
    assert "Open referenced note:" not in rendered
    assert rendered.index("note-source-arrow") < rendered.index("embedded root")


@pytest.mark.parametrize(("written", "shown_as"), [
    ("[[{id}]]", "note-reference-link-mode"),
    ("![[{id}]]", "note-embed-block"),
])
def test_a_reference_amid_text_is_what_its_written_form_says(
    monkeypatch: pytest.MonkeyPatch, written: str, shown_as: str,
) -> None:
    # The written form decides, anywhere in the text: ![[...]] embeds, [[...]] links.
    token = written.format(id=TARGET_ID)
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"<div>blah {token} yada</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>embedded root</div>", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID, TARGET_ID]})

    rendered = state.payloads[HOST_ID]["content"]
    other = {"note-reference-link-mode", "note-embed-block"} - {shown_as}
    assert other.pop() not in rendered
    assert rendered.index("blah") < rendered.index(shown_as) < rendered.index("yada")
    # A note holding more than one embed is not a holder: it doesn't fold as its source.
    assert "note-reference-only" not in rendered


@pytest.mark.parametrize("content,standalone", [
    (f"![[{TARGET_ID}]]", True),
    # An extra line is content: the reference is a link.
    (f"<div><span>![[{TARGET_ID}]]</span></div><div><br></div>", False),
    # A line break ending the reference's own line is the editor's placeholder.
    (f"<div>![[{TARGET_ID}]]<br></div>", True),
    # Alone, [[...]] is still a link: only ![[...]] embeds.
    (f"<p>[[{TARGET_ID}]]</p>", False),
    (f"text<div>![[{TARGET_ID}]]</div>", False),
    (f'![[{TARGET_ID}]]<img src="data:image/png;base64,aA==">', False),
    (f"![[{TARGET_ID}]] ![[{TARGET_ID}]]", False),
    (f"![[{MISSING_ID}]]", False),
])
@pytest.mark.parametrize("collapsed", [True, False])
def test_standalone_reference_and_source_chrome(monkeypatch, content, standalone, collapsed):
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, collapsed, content, ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, collapsed, "Source<br>second line", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)})
    host = state.payloads[HOST_ID]["content"]
    source = state.payloads[TARGET_ID]["content"]
    assert ('class="note-reference-only"' in host) is standalone
    assert ('class="note-with-backlinks"' in source) is (TARGET_ID in content)
    assert "note-backlinks-link" not in host
    if TARGET_ID in content:
        assert f'data-source-note-id="{TARGET_ID}"' in source
        assert source.index("\u2196") < source.index("Source")


def test_backlink_arrow_updates_when_last_reference_is_removed(monkeypatch):
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"![[{TARGET_ID}]]", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "Source", ""),
    }
    children = {None: list(notes)}
    before = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent=children)
    notes[HOST_ID].content = "No reference anymore"
    after = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent=children)
    assert "note-backlinks-link" in before.payloads[TARGET_ID]["content"]
    assert "note-backlinks-link" not in after.payloads[TARGET_ID]["content"]
    assert before.payloads[TARGET_ID]["hash"] != after.payloads[TARGET_ID]["hash"]


def test_editing_source_omits_reference_chrome(monkeypatch):
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"![[{TARGET_ID}]]", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "Source", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)},
                       editing_note_id=TARGET_ID)
    assert state.payloads[TARGET_ID]["content"] == "Source"


def test_a_self_reference_does_not_create_a_source_arrow(monkeypatch):
    notes = {TARGET_ID: _Note(TARGET_ID, None, None, None, False, f"![[{TARGET_ID}]]", "")}
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)})
    assert "note-backlinks-link" not in state.payloads[TARGET_ID]["content"]


def test_a_note_id_link_beside_a_square_formatting_wrapper_is_still_a_link(monkeypatch):
    # A [[...]] holding exactly a note id is always a link (docs/ui/references.md).
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"[[{TARGET_ID}]]", "[[@red]]"),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "Target", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)})
    assert "note-backlinks-link" in state.payloads[TARGET_ID]["content"]
    assert "note-reference-link-mode" in state.payloads[HOST_ID]["content"]


def test_a_link_nested_in_a_square_formatting_wrapper_still_renders(monkeypatch):
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False,
                       f"<div>[[see [[{TARGET_ID}]] here]]</div>", "[[@red]]"),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "Target", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)})
    rendered = state.payloads[HOST_ID]["content"]
    assert "note-reference-block" in rendered
    assert f"[[{TARGET_ID}]]" not in rendered


def test_view_rendering_never_exposes_remote_image_source_to_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_url = "https://images.example/private-tracker.png"
    notes = {
        HOST_ID: _Note(
            HOST_ID,
            None,
            None,
            None,
            False,
            f'<div><img src="{remote_url}" alt="remote"></div>',
            "",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert remote_url not in rendered
    assert re.search(
        r'data-remote-image-proxy-src="/api2/remote-images/[A-Za-z0-9_-]{32}"',
        rendered,
    ) is not None
    assert re.search(r"<img[^>]+\ssrc=", rendered) is None


@pytest.mark.parametrize("invisible", ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])
def test_an_invisible_character_beside_a_reference_leaves_it_the_whole_note(
    monkeypatch: pytest.MonkeyPatch, invisible: str,
) -> None:
    # A zero-width space (left by ⌘B with nothing selected, or pasted) cannot be
    # seen in the editor: the note is still only its reference, shown as an embed.
    notes = {
        HOST_ID: _Note(
            HOST_ID, None, None, TARGET_ID, False, f"<div><strong>{invisible}</strong>![[{TARGET_ID}]]</div>", "",
        ),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>embedded first line</div>", ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID, TARGET_ID]})

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-embed-block" in rendered
    assert "note-reference-link-mode" not in rendered


@pytest.mark.parametrize("collapsed", [True, False])
def test_a_note_that_is_only_a_reference_folds_as_its_source(
    monkeypatch: pytest.MonkeyPatch, collapsed: bool,
) -> None:
    # The note shows its source's collapse, whatever its own saved state: folded
    # to the source's first line, or the whole source with its children.
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, not collapsed, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(
            TARGET_ID,
            None,
            HOST_ID,
            None,
            collapsed,
            "<div>embedded first line</div><div>embedded hidden line</div>",
            "",
        ),
        CHILD_ID: _Note(CHILD_ID, TARGET_ID, None, None, False, "<div>embedded child</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID], TARGET_ID: [CHILD_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert state.payloads[HOST_ID]["flags"]["isCollapsed"] is collapsed
    assert "embedded first line" in rendered
    assert ("embedded hidden line" in rendered) is not collapsed
    assert ("embedded child" in rendered) is not collapsed
    # Folded, the embed is still an embed, its source folded (docs/ui/references.md).
    assert ("note-embed-collapsed" in rendered) is collapsed
    assert "note-reference-link-mode" not in rendered


@pytest.mark.parametrize("collapsed", [True, False])
def test_an_embedded_child_shows_its_saved_collapse_with_an_arrow(
    monkeypatch: pytest.MonkeyPatch, collapsed: bool,
) -> None:
    # Collapse is shared: a note inside an embed shows the state saved for it,
    # with an arrow that toggles that same state.
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>embedded root</div>", ""),
        CHILD_ID: _Note(CHILD_ID, TARGET_ID, None, None, collapsed, "<div>embedded child</div>", ""),
        OTHER_ID: _Note(OTHER_ID, CHILD_ID, None, None, False, "<div>embedded grandchild</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID], TARGET_ID: [CHILD_ID], CHILD_ID: [OTHER_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    expanded, label = {True: ("false", "Expand note"), False: ("true", "Collapse note")}[collapsed]
    assert (
        f'<button type="button" class="note-embed-collapse-toggle" data-embed-collapse-note-id="{CHILD_ID}" '
        f'aria-expanded="{expanded}" aria-label="{label}"></button>'
    ) in rendered
    assert ("embedded grandchild" in rendered) is not collapsed


# A link inside another link is split apart when the HTML is read (by the
# sanitizer and by browsers alike), leaving empty links behind.
_EMPTY_LINK_RE = re.compile(r"<a\b[^>]*></a>")


def test_a_collapsed_embed_of_a_note_that_is_only_an_embed_shows_the_source_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HOST embeds OTHER, which only embeds TARGET: the collapsed HOST shows the
    # embeds, still embeds, down to TARGET's first line in its own formatting.
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, OTHER_ID, True, f"<div>![[{OTHER_ID}]]</div>", ""),
        OTHER_ID: _Note(OTHER_ID, None, HOST_ID, TARGET_ID, True, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(
            TARGET_ID, None, OTHER_ID, None, True,
            "<div>The Living Labyrinth</div><div>hidden line</div>", "@heading @green",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID, OTHER_ID, TARGET_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert _EMPTY_LINK_RE.search(rendered) is None
    assert _visible_text(rendered) == "The Living Labyrinth"
    assert "meta-global meta-green meta-heading" in rendered
    assert "hidden line" not in rendered
    assert f'data-embed-note-id="{OTHER_ID}"' in rendered
    assert f'data-embed-note-id="{TARGET_ID}"' in rendered
    assert "note-reference-link-mode" not in rendered


def test_a_collapsed_embed_whose_first_line_holds_a_link_keeps_one_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The source's first line links to another note: the folded embed shows that
    # line as the source shows it, the link as a link.
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, OTHER_ID, True, f"<div>![[{OTHER_ID}]]</div>", ""),
        OTHER_ID: _Note(
            OTHER_ID, None, HOST_ID, TARGET_ID, True,
            f"<div>See [[{TARGET_ID}]] here</div><div>hidden line</div>", "@green",
        ),
        TARGET_ID: _Note(TARGET_ID, None, OTHER_ID, None, False, "<div>The Living Labyrinth</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID, OTHER_ID, TARGET_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert _EMPTY_LINK_RE.search(rendered) is None
    assert _visible_text(rendered) == "See The Living Labyrinth here"
    assert f'data-embed-note-id="{OTHER_ID}"' in rendered
    assert "hidden line" not in rendered


def test_a_collapsed_note_starting_with_an_embed_shows_the_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The embed is the first line: folded, it is still the embed, its source folded
    # to its first line (a folded note is one line); the host's later lines are hidden.
    notes = {
        HOST_ID: _Note(
            HOST_ID,
            None,
            None,
            TARGET_ID,
            True,
            f"<div>![[{TARGET_ID}]]</div><div>hidden host line</div>",
            "",
        ),
        TARGET_ID: _Note(
            TARGET_ID,
            None,
            HOST_ID,
            None,
            False,
            "<div>referenced first line</div><div>referenced second line</div>",
            "",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-reference-link-mode" not in rendered
    assert "note-embed-block" in rendered
    assert "referenced first line" in rendered
    assert "referenced second line" not in rendered
    assert "hidden host line" not in rendered


def test_embed_reference_missing_uuid_shows_missing_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>![[{MISSING_ID}]]</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-embed-missing" in rendered
    assert f"Missing reference: {MISSING_ID}" in rendered
    assert "note-reference-toggle" not in rendered


def test_link_reference_missing_uuid_shows_missing_marker_without_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>[[{MISSING_ID}]]</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-embed-missing" in rendered
    assert f"Missing reference: {MISSING_ID}" in rendered
    assert "note-reference-toggle" not in rendered


def test_non_uuid_double_square_tokens_remain_literal_without_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = {
        HOST_ID: _Note(
            HOST_ID,
            None,
            None,
            None,
            False,
            "<div>e.g. [[3]] with tag [[@counter]]</div>",
            "",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "[[3]]" in rendered
    assert "[[@counter]]" in rendered
    assert "note-embed-missing" not in rendered
    assert "Missing reference:" not in rendered


def test_scoped_double_square_latex_is_not_treated_as_link_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = {
        HOST_ID: _Note(
            HOST_ID,
            None,
            None,
            None,
            False,
            "<div>enqueue is [[$O(N)$]]</div>",
            "[[@LaTeX]]",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "Missing reference: $O(N)$" not in rendered
    assert "note-embed-missing" not in rendered
    assert 'class="meta-latex meta-latex-inline"' in rendered
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">' in rendered


def test_embed_reference_cycle_shows_cycle_marker_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, None, None, False, f"<div>![[{HOST_ID}]]</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-embed-block" in rendered
    assert "note-embed-cycle" in rendered
    assert f"Circular reference: {HOST_ID}" in rendered


def test_plain_reference_renders_link_mode_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>prefix [[{TARGET_ID}]] suffix</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, None, None, False, "<div>linked first line</div><div>linked second line</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-reference-link-mode" in rendered
    assert "note-reference-link" in rendered
    assert "linked first line" in rendered
    assert "linked second line" not in rendered
    assert 'data-ref-mode="link"' in rendered
    assert "note-reference-toggle" not in rendered


def test_link_reference_renders_cached_standalone_url_title(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://www.youtube.com/watch?v=abc123"
    connection = _bootstrap_cached_link_title(url=url, title="A Useful Video")
    try:
        notes = {
            HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>See [[{TARGET_ID}]]</div>", ""),
            TARGET_ID: _Note(TARGET_ID, None, None, None, False, f"<div>{url}</div>", ""),
        }
        state = _state_for(
            monkeypatch=monkeypatch,
            notes=notes,
            children_by_parent={None: [HOST_ID, TARGET_ID]},
        )
    finally:
        link_title_store.reset()
        connection.close()

    rendered = state.payloads[HOST_ID]["content"]
    assert '<span class="note-reference-link-title">' in rendered
    assert '<span class="link-title-text">A Useful Video</span>' in rendered
    assert '<span class="link-title-domain"> · youtube.com</span>' in rendered
    assert url not in rendered


def test_link_reference_keeps_inline_url_preview_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://www.youtube.com/watch?v=abc123"
    connection = _bootstrap_cached_link_title(url=url, title="A Useful Video")
    try:
        notes = {
            HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>See [[{TARGET_ID}]]</div>", ""),
            TARGET_ID: _Note(TARGET_ID, None, None, None, False, f"<div>Watch {url}</div>", ""),
        }
        state = _state_for(
            monkeypatch=monkeypatch,
            notes=notes,
            children_by_parent={None: [HOST_ID, TARGET_ID]},
        )
    finally:
        link_title_store.reset()
        connection.close()

    rendered = state.payloads[HOST_ID]["content"]
    assert f'<span class="note-reference-link-title">Watch {url}</span>' in rendered
    assert 'class="link-title-text"' not in rendered
    assert "A Useful Video" not in rendered


def test_link_mode_preview_strips_nested_reference_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    nested_ref_id = "69dc0ad7-6ad6-4be9-8ad8-7c30704e5c1a"
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>See [[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(
            TARGET_ID,
            None,
            None,
            None,
            False,
            f"<div>blah ![[{nested_ref_id}]]</div><div>linked second line</div>",
            "",
        ),
        nested_ref_id: _Note(nested_ref_id, None, None, None, False, "<div>child</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID, nested_ref_id]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert "note-reference-link-mode" in rendered
    assert "blah" in rendered
    assert nested_ref_id not in rendered


def test_multiple_references_expose_stable_occurrence_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>[[{TARGET_ID}]] ![[{CHILD_ID}]] [[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, None, CHILD_ID, False, "<div>B</div>", ""),
        CHILD_ID: _Note(CHILD_ID, None, TARGET_ID, None, False, "<div>C</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID, CHILD_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert rendered.count('data-ref-occurrence="0"') == 1
    assert rendered.count('data-ref-occurrence="1"') == 1
    assert rendered.count('data-ref-occurrence="2"') == 1


def test_edit_mode_keeps_literal_embed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>embedded</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID, TARGET_ID]},
        editing_note_id=HOST_ID,
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert f"![[{TARGET_ID}]]" in rendered
    assert "note-embed-block" not in rendered


def test_view_mode_marks_inline_image_occurrences_for_context_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = {
        HOST_ID: _Note(
            HOST_ID,
            None,
            None,
            None,
            False,
            '<div><img src="one.png"><img src="two.png"></div>',
            "",
        ),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
    )

    rendered = state.payloads[HOST_ID]["content"]
    assert 'data-inline-image-occurrence="0"' in rendered
    assert 'data-inline-image-occurrence="1"' in rendered


def test_edit_mode_keeps_inline_images_free_of_render_only_occurrence_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = '<div><img src="one.png"></div>'
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, content, ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent={None: [HOST_ID]},
        editing_note_id=HOST_ID,
    )

    assert state.payloads[HOST_ID]["content"] == content


def test_embed_host_hash_changes_when_referenced_note_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, False, f"<div>![[{TARGET_ID}]]</div>", ""),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, "<div>before</div>", ""),
    }
    children_by_parent = {None: [HOST_ID, TARGET_ID]}
    state_one = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent=children_by_parent,
    )
    first_hash = state_one.payloads[HOST_ID]["hash"]

    notes[TARGET_ID].content = "<div>after</div>"
    state_two = _state_for(
        monkeypatch=monkeypatch,
        notes=notes,
        children_by_parent=children_by_parent,
    )
    second_hash = state_two.payloads[HOST_ID]["hash"]

    assert first_hash != second_hash


@pytest.mark.parametrize('is_editing', [False, True])
@pytest.mark.parametrize('content', ['<div>body {{reference}}</div>', '<p>body</p><p>{{reference}}</p><p>next</p>'])
def test_footnote_view_transform_leaves_edit_content_raw(monkeypatch, is_editing, content):
    editing_note_id = None
    if is_editing:
        editing_note_id = HOST_ID
    notes = {HOST_ID: _Note(HOST_ID, None, None, None, False, content, '{{@footnote}}')}
    state = _state_for(
        monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID]},
        editing_note_id=editing_note_id,
    )
    rendered = state.payloads[HOST_ID]['content']
    if is_editing:
        assert rendered == content
    else:
        assert 'data-footnote-number="1"' in rendered
        assert '{{reference}}' not in rendered
        assert 'body<sup ' in rendered
    assert notes[HOST_ID].content == content


@pytest.mark.parametrize("content", [
    "blah blah{{dis}}{{also dat}}{{third}}",
    "blah blah{{dis}}{{also dat}}{{third}}<br>Later prose{{fourth}}",
    "<div>blah blah</div><div>{{dis}}</div><div>{{also dat}}</div><div>{{third}}</div><div>Later prose{{fourth}}</div>",
])
def test_collapsed_embed_preview_preserves_source_footnote_numbers(monkeypatch, content):
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, TARGET_ID, True, f"![[{TARGET_ID}]]", ""),
        # The note folds as its source: the source is collapsed.
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, True, content, "{{@footnote}}"),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: list(notes)})
    # Folded, the embed is still an embed, showing its source folded as the list
    # shows it (main.css clips a folded footnote note to its first line).
    preview = state.payloads[HOST_ID]["content"]
    assert "note-embed-collapsed" in preview
    assert "note-reference-link-mode" not in preview
    assert "meta-footnotes-note" in preview
    for number in [1, 2, 3]:
        assert f'data-footnote-number="{number}"' in preview
    assert '{{' not in preview


def test_collapsed_preview_keeps_footnotes_from_following_source_paragraphs(monkeypatch):
    content = '<div>blah blah</div><div>{{dis}}</div><div>{{also dat}}</div><div>{{third}}</div>'
    notes = {HOST_ID: _Note(HOST_ID, None, None, None, True, content, '{{@footnote}}')}
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID]})
    rendered = state.payloads[HOST_ID]['content']
    assert '<div>blah blah<sup' in rendered
    assert rendered.count('class="ai-chat-citation-marker meta-footnote-marker"') == 3
    assert 'data-footnote-reference="3"' in rendered
    assert state.payloads[HOST_ID]['flags']['isCollapsed'] is True


# A note that is only an embed folds when what it shows can fold: an arrow that
# changes nothing is not shown (2026-10-26, docs/ui/references.md).
_ONE_LINE = "<div>Almonds</div>"
_TWO_LINES = "<div>Almonds</div><div>raw, unsalted</div>"


def _holder_note(note_id: str, source_id: str) -> _Note:
    return _Note(note_id, None, None, None, False, f"<div>![[{source_id}]]</div>", "")


@pytest.mark.parametrize(
    ("source_content", "source_children", "holder_children", "can_fold"),
    [
        pytest.param(_ONE_LINE, [], [], False, id="one-line source"),
        pytest.param(_TWO_LINES, [], [], True, id="source with more lines"),
        pytest.param(_ONE_LINE, [CHILD_ID], [], True, id="one-line source with children"),
        pytest.param(_ONE_LINE, [], [CHILD_ID], True, id="holder with children of its own"),
    ],
)
def test_a_note_that_is_only_an_embed_folds_when_its_source_can(
    monkeypatch: pytest.MonkeyPatch,
    source_content: str, source_children: List[str], holder_children: List[str], can_fold: bool,
) -> None:
    notes = {
        HOST_ID: _holder_note(HOST_ID, TARGET_ID),
        TARGET_ID: _Note(TARGET_ID, None, HOST_ID, None, False, source_content, ""),
        CHILD_ID: _Note(CHILD_ID, None, None, None, False, "<div>kid</div>", ""),
    }
    children_by_parent: Dict[Optional[str], List[str]] = {
        None: [HOST_ID, TARGET_ID], TARGET_ID: source_children, HOST_ID: holder_children,
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent=children_by_parent)
    assert state.payloads[HOST_ID]["flags"]["isCollapsible"] is can_fold


@pytest.mark.parametrize(("source_content", "can_fold"), [(_ONE_LINE, False), (_TWO_LINES, True)])
def test_a_chain_of_embeds_folds_as_its_last_source(
    monkeypatch: pytest.MonkeyPatch, source_content: str, can_fold: bool,
) -> None:
    notes = {
        HOST_ID: _holder_note(HOST_ID, OTHER_ID),
        OTHER_ID: _holder_note(OTHER_ID, TARGET_ID),
        TARGET_ID: _Note(TARGET_ID, None, None, None, False, source_content, ""),
    }
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [HOST_ID, OTHER_ID, TARGET_ID]})
    assert state.payloads[HOST_ID]["flags"]["isCollapsible"] is can_fold
    assert state.payloads[OTHER_ID]["flags"]["isCollapsible"] is can_fold


@pytest.mark.parametrize(("source_content", "has_arrow"), [(_ONE_LINE, False), (_TWO_LINES, True)])
def test_inside_an_embed_a_note_that_is_only_an_embed_folds_when_its_source_can(
    monkeypatch: pytest.MonkeyPatch, source_content: str, has_arrow: bool,
) -> None:
    # HOST embeds OTHER, whose child CHILD only embeds TARGET.
    notes = {
        HOST_ID: _holder_note(HOST_ID, OTHER_ID),
        OTHER_ID: _Note(OTHER_ID, None, None, None, False, "<div>Snacks</div>", ""),
        CHILD_ID: _holder_note(CHILD_ID, TARGET_ID),
        TARGET_ID: _Note(TARGET_ID, None, None, None, False, source_content, ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch, notes=notes,
        children_by_parent={None: [HOST_ID, OTHER_ID, TARGET_ID], OTHER_ID: [CHILD_ID]},
    )
    rendered = state.payloads[HOST_ID]["content"]
    assert (f'data-embed-collapse-note-id="{CHILD_ID}"' in rendered) is has_arrow


@pytest.mark.parametrize(
    ("embeds_each_other", "holder_children", "can_fold"),
    [
        pytest.param(False, [], False, id="deleted source"),
        pytest.param(True, [], False, id="notes that embed each other"),
        pytest.param(True, [CHILD_ID], True, id="notes that embed each other, with children"),
    ],
)
def test_an_embed_with_no_source_to_show_folds_only_with_children(
    monkeypatch: pytest.MonkeyPatch, embeds_each_other: bool, holder_children: List[str], can_fold: bool,
) -> None:
    notes = {
        HOST_ID: _holder_note(HOST_ID, MISSING_ID),
        CHILD_ID: _Note(CHILD_ID, None, None, None, False, "<div>kid</div>", ""),
    }
    roots = [HOST_ID]
    if embeds_each_other:
        notes[HOST_ID] = _holder_note(HOST_ID, TARGET_ID)
        notes[TARGET_ID] = _holder_note(TARGET_ID, HOST_ID)
        roots.append(TARGET_ID)
    state = _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: roots, HOST_ID: holder_children})
    assert state.payloads[HOST_ID]["flags"]["isCollapsible"] is can_fold


# A folded note shows its first line as it is shown: an embed always starts a line
# of its own, and stays an embed folded (only the ! makes an embed; agreed
# 2026-10-26, docs/ui/references.md). SNACK embeds ALMONDS (one line) or NUTS
# (two lines).
SNACK_ID = "55555555-5555-5555-5555-555555555555"
ALMONDS_ID = "66666666-6666-6666-6666-666666666666"
CASHEWS_ID = "77777777-7777-7777-7777-777777777777"
NUTS_ID = "88888888-8888-8888-8888-888888888888"
_EMBEDDED_NOTES = {
    ALMONDS_ID: "<div>Almonds</div>",
    CASHEWS_ID: "<div>Cashews</div>",
    NUTS_ID: "<div>Nuts</div><div>Almonds, cashews</div>",
}


def _snack_state(monkeypatch: pytest.MonkeyPatch, snack_content: str, *, folded: bool, nuts_folded: bool):
    notes = {SNACK_ID: _Note(SNACK_ID, None, None, None, folded, snack_content, "")}
    for note_id, content in _EMBEDDED_NOTES.items():
        notes[note_id] = _Note(note_id, None, None, None, note_id == NUTS_ID and nuts_folded, content, "")
    return _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent={None: [SNACK_ID, *_EMBEDDED_NOTES]})


def _visible_text(rendered: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", rendered).split())


@pytest.mark.parametrize(
    ("snack_content", "folded_text"),
    [
        pytest.param(f"<div>Snack: ![[{ALMONDS_ID}]]</div>", "Snack:", id="1 text, then an embed"),
        pytest.param(f"<div>Snack: ![[{ALMONDS_ID}]] and more</div>", "Snack:", id="2 text, an embed, text"),
        pytest.param(f"<div>Snack: ![[{ALMONDS_ID}]]</div><div>Daily</div>", "Snack:", id="3 a second line"),
        pytest.param(f"<div>Snack: ![[{ALMONDS_ID}]] ![[{CASHEWS_ID}]]</div>", "Snack:", id="4 two embeds"),
    ],
)
def test_a_folded_note_shows_the_text_before_its_embed(
    monkeypatch: pytest.MonkeyPatch, snack_content: str, folded_text: str,
) -> None:
    state = _snack_state(monkeypatch, snack_content, folded=True, nuts_folded=False)
    payload = state.payloads[SNACK_ID]
    assert payload["flags"]["isCollapsible"] is True
    assert payload["flags"]["isCollapsed"] is True
    assert _visible_text(payload["content"]) == folded_text
    assert "note-reference-block" not in payload["content"]


def test_a_note_starting_with_an_embed_folds_to_the_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    # 5: the embed is the first line; folded, it is still the embed.
    state = _snack_state(monkeypatch, f"<div>![[{ALMONDS_ID}]] for snack</div>", folded=True, nuts_folded=False)
    payload = state.payloads[SNACK_ID]
    assert payload["flags"]["isCollapsible"] is True
    assert _visible_text(payload["content"]) == "Almonds"
    assert "note-embed-block" in payload["content"]
    assert f'data-embed-note-id="{ALMONDS_ID}"' in payload["content"]
    assert "note-reference-link-mode" not in payload["content"]


def test_a_folded_note_starting_with_an_embed_shows_the_embed_folded(monkeypatch: pytest.MonkeyPatch) -> None:
    # A folded note is one line (2026-10-27): the embed on it shows its note folded,
    # though NUTS itself is unfolded.
    state = _snack_state(monkeypatch, f"<div>![[{NUTS_ID}]] for snack</div>", folded=True, nuts_folded=False)
    rendered = state.payloads[SNACK_ID]["content"]
    assert _visible_text(rendered) == "Nuts"
    assert "note-embed-root note-embed-collapsed" in rendered


def test_a_folded_note_that_is_only_an_embed_shows_the_folded_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    # 6: the note folds with its source; folded, it shows the embed with the source folded.
    state = _snack_state(monkeypatch, f"<div>![[{NUTS_ID}]]</div>", folded=False, nuts_folded=True)
    payload = state.payloads[SNACK_ID]
    assert payload["flags"]["isCollapsible"] is True
    assert payload["flags"]["isCollapsed"] is True
    assert _visible_text(payload["content"]) == "Nuts"
    assert "note-embed-held" in payload["content"]
    assert f'data-embed-note-id="{NUTS_ID}"' in payload["content"]
    assert "note-reference-link-mode" not in payload["content"]


def test_a_link_stays_on_its_line_and_does_not_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    # 8
    state = _snack_state(monkeypatch, f"<div>Snack: [[{ALMONDS_ID}]]</div>", folded=False, nuts_folded=False)
    assert state.payloads[SNACK_ID]["flags"]["isCollapsible"] is False


def test_inside_an_embed_a_folded_note_shows_the_text_before_its_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    # 9: HOST embeds OTHER, whose folded child SNACK reads "Snack: ![[ALMONDS]]".
    notes = {
        HOST_ID: _Note(HOST_ID, None, None, None, False, f"<div>![[{OTHER_ID}]]</div>", ""),
        OTHER_ID: _Note(OTHER_ID, None, None, None, False, "<div>Pantry</div>", ""),
        SNACK_ID: _Note(SNACK_ID, OTHER_ID, None, None, True, f"<div>Snack: ![[{ALMONDS_ID}]]</div>", ""),
        ALMONDS_ID: _Note(ALMONDS_ID, None, None, None, False, "<div>Almonds</div>", ""),
    }
    state = _state_for(
        monkeypatch=monkeypatch, notes=notes,
        children_by_parent={None: [HOST_ID, OTHER_ID, ALMONDS_ID], OTHER_ID: [SNACK_ID]},
    )
    rendered = state.payloads[HOST_ID]["content"]
    assert f'data-embed-collapse-note-id="{SNACK_ID}"' in rendered
    assert f'data-embed-note-id="{ALMONDS_ID}"' not in rendered
    assert _visible_text(rendered) == "Pantry Snack:"
