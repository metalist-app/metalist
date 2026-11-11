"""Embedded searches, ![[search:…]] (docs/ready-to-build/search-links.md §11)."""
from __future__ import annotations

import re

import pytest

from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.security.rendered_html import sanitize_rendered_html
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.embedded_references import (
    CredentialDisplay,
    collect_active_reference_tokens,
    first_line_preview,
    render_note_content_with_embeds,
)
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.snapshot import _SnapshotTraversalCache, _new_embed_render_context, resolve_search_scope
from app.usecases.create_note import apply_insert_note

_RESULT_RE = re.compile(r'data-result-note-id="([^"]+)"')


@pytest.fixture
def live_database(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    clear_encryption_key()
    set_encryption_required(False)
    clear_cache()
    store.reset()
    file_registry.reset()
    session = SafeSession()
    auth_service.AuthService(session).initialize_settings()
    bootstrap_ontology_rules_store(connection=session.connection())
    store.load_from_db(None, prefetched_rows=[])
    yield session
    session.close()
    store.reset()
    clear_cache()
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _note(note_id: str, previous_id: str | None, *, content: str, tags: str) -> None:
    apply_insert_note(note_id, None, previous_id, None, "", content=content, tags=tags, proposed_tags="")


def _drawn(note_id: str) -> str:
    record = store.get_note(note_id)
    context = _new_embed_render_context(_SnapshotTraversalCache(), is_shown_in_gallery=lambda gallery_note_id, note_id: True)
    return sanitize_rendered_html(render_note_content_with_embeds(
        note_id=note_id, content_html=record.content, tags=record.tags, context=context,
        static_export=False, credentials=CredentialDisplay.DOTS,
    ))


def _chores(count: int) -> list[str]:
    note_ids = []
    previous = None
    for index in range(count):
        note_id = f"chore-{index:02d}"
        _note(note_id, previous, content=f"<div>Chore {index:02d}</div><div>details</div>", tags="zzchore")
        note_ids.append(note_id)
        previous = note_id
    return note_ids


def test_an_embedded_search_shows_its_first_ten_results_as_first_lines_then_how_many_more(live_database) -> None:
    chores = _chores(12)
    _note("dash", chores[-1], content="<div>Dashboard</div><div>![[search:zzchore|Open chores]]</div>", tags="")

    drawn = _drawn("dash")

    assert 'class="note-search-embed"' in drawn
    assert ">Open chores<" in drawn and "· 12" in drawn
    # The first ten in the list's order, each as its note's first line only.
    assert _RESULT_RE.findall(drawn) == chores[:10]
    assert "Chore 00" in drawn and "details" not in drawn
    assert "… and 2 more" in drawn


def test_a_search_finding_nothing_shows_its_heading_and_zero(live_database) -> None:
    _note("dash", None, content="<div>![[search:zznothing]]</div>", tags="")
    drawn = _drawn("dash")
    assert ">zznothing<" in drawn and "· 0" in drawn
    assert _RESULT_RE.findall(drawn) == [] and "more" not in drawn


def test_a_result_holding_an_embedded_search_shows_only_its_heading(live_database) -> None:
    _note("inner", None, content="<div>![[search:zzchore|Inner]]</div>", tags="zzpanel")
    _chores(2)
    _note("dash", None, content="<div>![[search:zzpanel]]</div>", tags="")
    drawn = _drawn("dash")
    assert _RESULT_RE.findall(drawn) == ["inner"]
    # The inner search draws its heading, never its own results: no search inside a search.
    assert ">Inner<" in drawn
    assert drawn.count('class="note-search-embed-result"') == 1


def test_an_embedded_search_is_never_a_reference_and_reads_its_text_in_a_first_line() -> None:
    assert collect_active_reference_tokens("<div>![[search:work|Work]]</div>") == []
    assert first_line_preview("<div>![[search:work -archive|Current work]]</div>") == "Current work"


def test_a_search_scope_with_no_root_order_given_finds_its_own(live_database) -> None:
    """Alphabetize Root Notes, Move to Top and a notes route ask with no order: it was a TypeError."""
    _chores(2)
    scope = resolve_search_scope(search="zzchore", editing_note_id=None, sort_mode="normal", date_filter=None, ordered_root_ids=None)
    assert scope.matched_note_ids == {"chore-00", "chore-01"}


def test_only_the_top_match_of_each_branch_is_a_result(live_database) -> None:
    """A child matching through its parent is the parent's detail, not an item of its own (agreed
    2026-11-11): the results are each branch's top match, as the list shows them folded."""
    apply_insert_note("plan", None, None, None, "", content="<div>Plan</div>", tags="zzbranch", proposed_tags="")
    apply_insert_note("detail", "plan", None, None, "", content="<div>Detail</div>", tags="zzbranch", proposed_tags="")
    apply_insert_note("other", None, "plan", None, "", content="<div>Other</div>", tags="", proposed_tags="")
    apply_insert_note("lone", "other", None, None, "", content="<div>Lone</div>", tags="zzbranch", proposed_tags="")
    _note("dash", "other", content="<div>![[search:zzbranch]]</div>", tags="")

    drawn = _drawn("dash")

    assert _RESULT_RE.findall(drawn) == ["plan", "lone"]
    assert "· 2" in drawn
