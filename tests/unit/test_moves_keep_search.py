"""A note moved to another parent never disappears from the search it was found by
(docs/ready-to-build/drag-across-levels.md, §6): it gets, as its own tags, the tags it
needs to keep matching, and only those. A note that did not match (shown only as the
ancestor of a match) gets nothing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.security.sensitive_cache import enable_sensitive_caches
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.search_index import search_index
from app.services.store import store as notes
from app.usecases.create_note import apply_insert_note
from app.usecases.outdent import CmdOutdent
from app.usecases.undo import CmdUndo


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
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


def _outline(*notes: tuple[str, str | None, str]) -> None:
    """Adds the notes (name, parent, tags) in order, each after the previous one under
    the same parent."""
    last_child: dict[str | None, str] = {}
    for name, parent, tags in notes:
        previous = None
        if parent in last_child:
            previous = last_child[parent]
        apply_insert_note(name, parent, previous, None, "test-token", content=f"<div>{name}</div>", tags=tags, proposed_tags="")
        last_child[parent] = name


def _outdent(name: str, search: str) -> None:
    CmdOutdent(
        note_id=name, search_query=search, token="test-token", client_id="client-1",
        undo_context="undo-1", viewport={"scrollY": 0, "scrollAnchor": None},
    ).execute()


def test_outdented_under_a_note_that_is_not_a_root_it_stays_in_the_search(vault) -> None:
    _outline(("Home", None, ""), ("Cooking", "Home", "recipes"), ("Pasta", "Cooking", ""))
    assert "Pasta" in search_index.query_note_ids("recipes")

    _outdent("Pasta", "recipes")

    assert notes.get("Pasta").parent_id == "Home"
    assert notes.get("Pasta").tags == "recipes"
    assert "Pasta" in search_index.query_note_ids("recipes")


def test_a_match_through_a_child_of_a_root_is_kept_too(vault) -> None:
    _outline(
        ("Home", None, ""), ("Kitchen", "Home", ""), ("Cooking", "Kitchen", "recipes"),
        ("Pasta", "Cooking", "dinner"),
    )

    _outdent("Pasta", "recipes dinner")

    assert notes.get("Pasta").parent_id == "Kitchen"
    assert notes.get("Pasta").tags == "dinner recipes"
    assert "Pasta" in search_index.query_note_ids("recipes dinner")


def test_a_note_that_still_inherits_the_tag_gets_nothing(vault) -> None:
    _outline(("Home", None, "recipes"), ("Cooking", "Home", "recipes"), ("Pasta", "Cooking", ""))

    _outdent("Pasta", "recipes")

    assert notes.get("Pasta").tags == ""
    assert "Pasta" in search_index.query_note_ids("recipes")


def test_a_note_shown_only_above_a_match_gets_nothing(vault) -> None:
    _outline(("Home", None, ""), ("Kitchen", "Home", ""), ("Cooking", "Kitchen", "recipes"))
    assert "Kitchen" not in search_index.query_note_ids("recipes")

    _outdent("Kitchen", "recipes")

    assert notes.get("Kitchen").parent_id is None
    assert notes.get("Kitchen").tags == ""


def test_with_or_the_note_keeps_the_part_of_the_search_it_matched(vault) -> None:
    _outline(("Home", None, ""), ("Cooking", "Home", "dinner"), ("Pasta", "Cooking", ""))

    _outdent("Pasta", "recipes OR dinner")

    assert notes.get("Pasta").tags == "dinner"
    assert "Pasta" in search_index.query_note_ids("recipes OR dinner")


def test_with_or_a_note_still_matching_another_part_gets_nothing(vault) -> None:
    _outline(("Home", None, ""), ("Cooking", "Home", "recipes"), ("Pasta", "Cooking", "dinner"))

    _outdent("Pasta", "recipes OR dinner")

    assert notes.get("Pasta").tags == "dinner"


def test_outdented_to_a_root_it_stays_in_the_search_as_before(vault) -> None:
    _outline(("Cooking", None, "recipes"), ("Pasta", "Cooking", ""))

    _outdent("Pasta", "recipes")

    assert notes.get("Pasta").parent_id is None
    assert notes.get("Pasta").tags == "recipes"


def test_undo_puts_back_the_place_and_the_tags(vault) -> None:
    _outline(("Home", None, ""), ("Cooking", "Home", "recipes"), ("Pasta", "Cooking", ""))
    _outdent("Pasta", "recipes")

    CmdUndo(client_id="client-1", token="test-token", undo_context="undo-1").execute()

    assert notes.get("Pasta").parent_id == "Cooking"
    assert notes.get("Pasta").tags == ""
