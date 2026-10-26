"""Typing `[[` in a note suggests notes to reference (docs/ui/references.md, "Suggestions";
agreed 2026-10-26). Four tiers, strictly in order:
an exact match on the first line, a fuzzy one (a small typo or a partial word), an exact match
in the content, a fuzzy one; ties go to the most recently edited note. Any note can be suggested,
child notes too, but not the one being edited. An @password note is never found or shown by the
password it holds: it is suggested by its parent's first line, shown masked."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.usecases.create_note as create_note_module
import app.usecases.update_content as update_content_module
from app.security.sensitive_cache import disable_and_clear_sensitive_caches, enable_sensitive_caches
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.content_formatting import CREDENTIAL_MASK
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.reference_suggestions import REFERENCE_SUGGESTION_LIMIT, _catalog, suggest_references
from app.usecases.create_note import apply_insert_note

_START = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


class _Clock:
    """Each note is made (and so last edited) a day after the one before."""

    def __init__(self) -> None:
        self.made = 0

    def now(self, zone):  # noqa: ARG002 - the same signature as datetime.now
        self.made += 1
        return _START + timedelta(days=self.made)


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    clock = _Clock()
    monkeypatch.setattr(create_note_module, "datetime", clock)
    monkeypatch.setattr(update_content_module, "datetime", clock)
    clear_encryption_key()
    set_encryption_required(False)
    enable_sensitive_caches()
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


def _note(note_id: str, lines: list[str]) -> None:
    _note_under(note_id, lines, tags="", parent_id=None)


def _note_under(note_id: str, lines: list[str], *, tags: str, parent_id: str | None) -> None:
    content = "".join(f"<div>{line}</div>" for line in lines)
    apply_insert_note(note_id, parent_id, None, None, "", content=content, tags=tags, proposed_tags="")


def _ids(query: str) -> list[str]:
    return [suggestion.note_id for suggestion in suggest_references(query=query, editing_note_id="editing")]


def test_the_four_tiers_in_order(notes) -> None:
    # Made newest last, so recency alone would put them in the opposite order.
    _note("exact-first-line", ["Bayes factor", "a note"])
    _note("fuzzy-first-line", ["Bayse factors", "with a typo"])
    _note("exact-content", ["Statistics", "the bayes factor compares two models"])
    _note("fuzzy-content", ["Odds", "a baye factr, misspelt"])
    _note("editing", ["The note being edited"])

    assert _ids("bayes factor") == ["exact-first-line", "fuzzy-first-line", "exact-content", "fuzzy-content"]


def test_a_partial_word_is_a_fuzzy_match(notes) -> None:
    _note("partial", ["Hyperparameter tuning"])
    _note("editing", ["The note being edited"])

    assert _ids("hyper tun") == ["partial"]


def test_ties_go_to_the_most_recently_edited(notes) -> None:
    _note("older", ["Trip plan for Japan"])
    _note("newer", ["Trip plan for Iceland"])
    _note("editing", ["The note being edited"])

    assert _ids("trip plan") == ["newer", "older"]


def test_a_content_match_shows_a_snippet_and_a_first_line_match_does_not(notes) -> None:
    _note("first", ["Bayes factor"])
    _note("content", ["Statistics", "Here the Bayes factor compares two models of the data"])
    _note("editing", ["The note being edited"])

    first, content = suggest_references(query="bayes factor", editing_note_id="editing")

    assert (first.first_line, first.snippet) == ("Bayes factor", "")
    assert content.first_line == "Statistics"
    assert content.snippet[content.highlight_start:content.highlight_end] == "Bayes factor"
    assert content.snippet.startswith("…") or content.snippet.startswith("Statistics")


def test_child_notes_are_suggested_and_the_edited_note_is_not(notes) -> None:
    _note("parent", ["Garden"])
    _note_under("child", ["Garden tomatoes"], tags="", parent_id="parent")
    _note("editing", ["Garden beds"])

    assert _ids("garden") == ["child", "parent"]


def test_a_password_is_found_by_its_parent_and_shown_masked(notes) -> None:
    _note("bank", ["Bank login"])
    _note_under("secret", ["hunter2-correct-horse"], tags="@password", parent_id="bank")
    _note("editing", ["The note being edited"])

    suggestions = suggest_references(query="bank", editing_note_id="editing")

    assert [(s.note_id, s.first_line, s.credential) for s in suggestions] == [
        ("bank", "Bank login", ""),
        ("secret", CREDENTIAL_MASK, "password"),
    ]
    assert suggestions[1].context == "Bank login"
    assert all("hunter2" not in s.snippet for s in suggestions)


def test_typing_a_password_never_finds_it(notes) -> None:
    _note("bank", ["Bank login"])
    _note_under("secret", ["hunter2-correct-horse"], tags="@password", parent_id="bank")
    _note("editing", ["The note being edited"])

    assert _ids("hunter2") == []
    assert _ids("correct horse") == []


def test_a_username_is_found_by_its_value(notes) -> None:
    _note("bank", ["Bank login"])
    _note_under("user", ["tom@example.org"], tags="@username", parent_id="bank")
    _note("editing", ["The note being edited"])

    (suggestion,) = suggest_references(query="tom@example", editing_note_id="editing")

    assert (suggestion.note_id, suggestion.first_line, suggestion.credential) == ("user", "tom@example.org", "username")


def test_no_match_suggests_nothing(notes) -> None:
    _note("one", ["Something else"])
    _note("editing", ["The note being edited"])

    assert _ids("zebra crossing") == []


def test_html_in_a_first_line_is_plain_text(notes) -> None:
    _note("markup", ["&lt;b&gt;bold&lt;/b&gt; idea"])
    _note("editing", ["The note being edited"])

    (suggestion,) = suggest_references(query="bold", editing_note_id="editing")

    assert suggestion.first_line == "<b>bold</b> idea"


def test_at_most_the_limit_and_nothing_on_an_empty_query_but_the_latest(notes) -> None:
    for index in range(REFERENCE_SUGGESTION_LIMIT + 3):
        _note(f"note-{index}", [f"Recipe {index}"])
    _note("editing", ["The note being edited"])

    assert len(_ids("recipe")) == REFERENCE_SUGGESTION_LIMIT
    latest = [f"note-{index}" for index in range(REFERENCE_SUGGESTION_LIMIT + 2, 2, -1)]
    assert _ids("") == latest[:REFERENCE_SUGGESTION_LIMIT]


def test_an_edited_note_is_found_by_its_new_text_and_comes_first(notes) -> None:
    _note("older", ["Packing list"])
    _note("edited", ["Shopping list"])
    _note("newer", ["Reading list"])
    _note("editing", ["The note being edited"])
    assert _ids("shopping") == ["edited"]

    update_content_module.apply_update_content("edited", "<div>Grocery list</div>", "", "")

    assert _ids("shopping") == []
    assert _ids("grocery") == ["edited"]
    assert _ids("list") == ["edited", "newer", "older"]


def test_a_typo_is_found_in_the_text_too(notes) -> None:
    _note("typo", ["Holiday", "we hired a canoe on the lake"])
    _note("editing", ["The note being edited"])

    (suggestion,) = suggest_references(query="cnaoe", editing_note_id="editing")

    assert suggestion.snippet[suggestion.highlight_start:suggestion.highlight_end] == "canoe"


def test_locking_empties_the_catalog_of_the_notes_text(notes) -> None:
    _note("one", ["Bank login"])
    _note("editing", ["The note being edited"])
    assert _ids("bank") == ["one"]

    disable_and_clear_sensitive_caches()
    try:
        assert _catalog.refreshed() == ({}, [])
        assert _ids("bank") == []
    finally:
        enable_sensitive_caches()
    assert _ids("bank") == ["one"]
