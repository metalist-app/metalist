"""Super tags: the tag bar suggests the values used last time (docs/design/tag-properties.md,
Suggestions; agreed case by case 2026-10-25). While a tag that has been used
with values is typed, the list offers it twice in a row: first the whole token from the most
recently created note that wrote values on it (units as written), then the bare tag, on the
empty bar too; once the whole tag name is typed, only the values are offered. Only
values written on a note's own tag line count: never inherited ones, never ones inside a
scope, never the note being edited. A tag never used with values is suggested as before."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.usecases.create_note as create_note_module
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.tag_suggestions import suggest_tags_for_note, suggest_tags_with_reasons_for_note
from app.usecases.create_note import apply_insert_note

_LIMIT = 20
_START = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


class _Clock:
    """Each note is created a day after the one before, so "most recent" never ties."""

    def __init__(self) -> None:
        self.created = 0

    def now(self, zone):  # noqa: ARG002 - the same signature as datetime.now
        self.created += 1
        return _START + timedelta(days=self.created)


@pytest.fixture
def live_database(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    monkeypatch.setattr(create_note_module, "datetime", _Clock())
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


def _note(note_id: str, *, tags: str, parent_id: str | None) -> None:
    apply_insert_note(note_id, parent_id, None, None, "", content=f"<div>{note_id}</div>", tags=tags,
                      proposed_tags="")


def _typed(prefix: str, *, note_id: str) -> list[str]:
    """What the tag bar shows; it sends what is typed as its last token."""
    return [suggestion.tag for suggestion in suggest_tags_with_reasons_for_note(
        note_id=note_id, anchors=[], explicit_tags=[prefix], prefix=prefix,
        content_html=store.get_note(note_id).content, limit=_LIMIT,
    )]


def _diet_log() -> None:
    _note("monday", tags="breakfast-burrito:calories=800:fat=10g journal", parent_id=None)
    _note("tuesday", tags="breakfast-burrito:calories=750:fat=12g:carbs=60G journal", parent_id=None)
    # Newer, but without values.
    _note("wednesday", tags="breakfast-burrito journal", parent_id=None)
    _note("today", tags="journal", parent_id=None)


def test_the_last_values_come_first_then_the_bare_tag(live_database) -> None:
    _diet_log()

    assert _typed("brea", note_id="today")[:2] == ["breakfast-burrito:calories=750:fat=12g:carbs=60G", "breakfast-burrito"]


def test_a_newer_note_with_other_values_changes_the_suggestion(live_database) -> None:
    _diet_log()
    _note("thursday", tags="breakfast-burrito:calories=900 journal", parent_id=None)

    assert _typed("brea", note_id="today")[:2] == ["breakfast-burrito:calories=900", "breakfast-burrito"]


def test_the_whole_tag_name_typed_offers_only_the_values(live_database) -> None:
    # The bare tag is what is already there (typed, or just accepted): offering it again
    # adds nothing (the maintainer, 2026-10-25).
    _diet_log()

    typed = _typed("breakfast-burrito", note_id="today")

    assert typed[0] == "breakfast-burrito:calories=750:fat=12g:carbs=60G"
    assert "breakfast-burrito" not in typed


def test_the_empty_bar_offers_the_values_first_too(live_database) -> None:
    # The note's text names the tag, so the empty bar suggests it: with values first, as
    # while typing (the maintainer's "no alcohol" note, 2026-10-25).
    _note("sober-week", tags="no-alcohol:days=19", parent_id=None)
    apply_insert_note("sleep", None, None, None, "", content="<div>no alcohol</div>", tags="",
                      proposed_tags="")

    empty_bar = [suggestion.tag for suggestion in suggest_tags_with_reasons_for_note(
        note_id="sleep", anchors=[], explicit_tags=[], prefix="",
        content_html=store.get_note("sleep").content, limit=_LIMIT,
    )]

    assert empty_bar[:2] == ["no-alcohol:days=19", "no-alcohol"]


def test_the_ai_reads_plain_tags_from_the_same_ranking(live_database) -> None:
    # The AI's tag vocabulary (agent/note_tag_suggestions.py) reads this ranking too: it
    # gets the tags alone, so last time's values never take its places.
    _note("sober-week", tags="no-alcohol:days=19", parent_id=None)
    apply_insert_note("sleep", None, None, None, "", content="<div>no alcohol</div>", tags="",
                      proposed_tags="")

    ranked = suggest_tags_for_note(
        note_id="sleep", anchors=[], explicit_tags=[], prefix="",
        content_html=store.get_note("sleep").content, limit=_LIMIT,
    )

    assert ranked[0] == "no-alcohol"
    assert all(":" not in tag for tag in ranked)


def test_inherited_and_scoped_values_are_never_used(live_database) -> None:
    _diet_log()
    # A child inherits its parent's tag, and a scope's values belong to the scope: neither
    # writes values on the note's own tag.
    _note("thursday", tags="journal", parent_id="tuesday")
    _note("friday", tags="(breakfast-burrito:calories=5)", parent_id=None)

    assert _typed("brea", note_id="today")[0] == "breakfast-burrito:calories=750:fat=12g:carbs=60G"


def test_the_note_being_edited_is_left_out(live_database) -> None:
    _diet_log()

    assert _typed("brea", note_id="tuesday")[0] == "breakfast-burrito:calories=800:fat=10g"


def test_a_tag_never_used_with_values_is_suggested_as_before(live_database) -> None:
    _diet_log()

    assert _typed("jour", note_id="today") == ["journal"]
    assert _typed("journal", note_id="today") == []


def test_the_last_values_say_where_they_come_from(live_database) -> None:
    _diet_log()

    suggestions = suggest_tags_with_reasons_for_note(
        note_id="today", anchors=[], explicit_tags=["brea"], prefix="brea",
        content_html=store.get_note("today").content, limit=_LIMIT,
    )

    assert suggestions[0].tag == "breakfast-burrito:calories=750:fat=12g:carbs=60G"
    assert suggestions[0].reasons == ("Values from the last note tagged breakfast-burrito (Oct 22, 2026)",)
