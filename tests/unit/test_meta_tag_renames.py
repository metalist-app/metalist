"""Four built-in tags renamed, converted once per database (agreed 2026-10-28):
`@highlighter`, `@llm`, `@list-bulleted` and `@list-numbered` become `@highlight`, `@ai`,
`@bullets` and `@numbered` in every note's tags and proposed tags and in the search
contexts' searches, keeping each note's updated time. The pass is recorded, so it runs
once; a restored older backup lacks the record and is converted again."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.content_cache as content_cache
import app.services.meta_tag_renames as meta_tag_renames
from app.db.notes_sql import insert_note
from app.db.schema import NAMESPACE_CONTENT_MIGRATIONS_TABLE
from app.db.session import begin_writer
from app.db.tab_state_sql import fetch_tab_state_row
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services.content_cache import clear_cache, populate_cache_from_db
from app.services.content_formatting import find_list_style, format_note_content_for_view, list_known_meta_tag_terms
from app.services.meta_tag_renames import (
    META_TAG_RENAMES_MIGRATION_ID,
    rename_meta_tags_in_search,
    rename_meta_tags_in_tag_bar,
)
from app.services.tab_state import tab_state_store
from app.utils.encryption import encrypt, get_encryption_service

_UPDATED_AT = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
_DEK_BYTES = 32


@pytest.mark.parametrize(("tags", "renamed"), [
    ("@highlighter @llm @list-bulleted @list-numbered", "@highlight @ai @bullets @numbered"),
    ("jogging ((@list-numbered)) {{@red @highlighter}}", "jogging ((@numbered)) {{@red @highlight}}"),
    ("@LLM @markdown", "@ai @markdown"),
    # A comment is text; a longer tag only starts with an old name.
    ("/* @llm */ @llm-notes @grey", "/* @llm */ @llm-notes @grey"),
])
def test_a_tag_bar_gets_the_new_names(tags: str, renamed: str) -> None:
    assert rename_meta_tags_in_tag_bar(tags) == renamed


@pytest.mark.parametrize(("query", "renamed"), [
    ("@llm", "@ai"),
    ("journal -@list-bulleted OR @Highlighter", "journal -@bullets OR @highlight"),
    # Quoted text is searched as typed.
    ('"@llm" @llm', '"@llm" @ai'),
    ("@llmish", "@llmish"),
])
def test_a_search_gets_the_new_names(query: str, renamed: str) -> None:
    assert rename_meta_tags_in_search(query) == renamed


@pytest.fixture
def namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    clear_cache()
    tab_state_store.clear_persisted_state_for_tests()
    try:
        yield
    finally:
        clear_cache()
        tab_state_store.clear_persisted_state_for_tests()
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def _store_raw(note_id: str, *, tags: str, proposed_tags: str, prev_id: str | None, next_id: str | None) -> None:
    """Stores a note as an older MetaList left it (a restore brings notes this way)."""
    content, nonce, tag = encrypt("<div>text</div>", "")
    tags_ciphertext, tags_nonce, tags_tag = encrypt(tags, "")
    proposed_ciphertext, proposed_nonce, proposed_tag = encrypt(proposed_tags, "")
    with begin_writer() as connection:
        insert_note(
            connection, note_id=note_id, content=content, encryption_nonce=nonce, encryption_tag=tag,
            tags=tags_ciphertext, tags_encryption_nonce=tags_nonce, tags_encryption_tag=tags_tag,
            proposed_tags=proposed_ciphertext, proposed_tags_encryption_nonce=proposed_nonce,
            proposed_tags_encryption_tag=proposed_tag,
            parent_id=None, prev_id=prev_id, next_id=next_id, is_collapsed=False,
            created_at=_UPDATED_AT, updated_at=_UPDATED_AT,
        )


def _search_for(query: str) -> None:
    snapshot = tab_state_store.snapshot()
    tab_id = snapshot["activeTabId"]
    tabs = snapshot["tabs"]
    tabs[tab_id]["searchQuery"] = query
    tab_state_store.update(
        active_tab_id=tab_id, tabs=tabs, tab_order=snapshot["tabOrder"], reference_views={},
        read_at_version=snapshot["version"],
    )


def _unlock() -> None:
    clear_cache()
    session = SafeSession()
    try:
        populate_cache_from_db(session, saved_searches=tab_state_store)
        session.commit()
    finally:
        session.close()


def _stored(note_id: str) -> tuple[str, str, str]:
    with begin_writer() as connection:
        row = connection.execute(
            "SELECT tags, tags_encryption_nonce, tags_encryption_tag, proposed_tags, "
            "proposed_tags_encryption_nonce, proposed_tags_encryption_tag, updated_at FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    tags, tags_nonce, tags_tag, proposed, proposed_nonce, proposed_tag, updated_at = row
    if tags_nonce is not None:
        tags = get_encryption_service().decrypt_from_storage(tags, tags_nonce, tags_tag)
    if proposed_nonce is not None:
        proposed = get_encryption_service().decrypt_from_storage(proposed, proposed_nonce, proposed_tag)
    return tags, proposed, updated_at


def _records() -> list[tuple[str, str, int]]:
    with begin_writer() as connection:
        return [tuple(row) for row in connection.execute(
            f"SELECT migration_id, status, converted_count FROM {NAMESPACE_CONTENT_MIGRATIONS_TABLE} "
            "WHERE migration_id = ?", (META_TAG_RENAMES_MIGRATION_ID,),
        ).fetchall()]


def _old_vault() -> None:
    _store_raw("answer", tags="@llm ((@highlighter))", proposed_tags="@list-numbered", prev_id=None, next_id="plain")
    _store_raw("plain", tags="journal @grey", proposed_tags="", prev_id="answer", next_id=None)
    _search_for("journal @llm")


def test_the_first_unlock_renames_tags_and_searches_and_records_it(namespace) -> None:
    _old_vault()
    _unlock()
    assert content_cache.get_cached_tags("answer") == "@ai ((@highlight))"
    assert content_cache.get_cached_proposed_tags("answer") == "@numbered"
    # Stored renamed, its updated time kept; a note without old names is left alone.
    assert _stored("answer") == ("@ai ((@highlight))", "@numbered", _UPDATED_AT.isoformat())
    assert _stored("plain") == ("journal @grey", "", _UPDATED_AT.isoformat())
    snapshot = tab_state_store.snapshot()
    assert snapshot["tabs"][snapshot["activeTabId"]]["searchQuery"] == "journal @ai"
    with begin_writer() as connection:
        assert "journal @ai" in fetch_tab_state_row(connection)["state_json"]
    # One note and one search changed.
    assert _records() == [(META_TAG_RENAMES_MIGRATION_ID, "complete", 2)]


def test_later_unlocks_do_not_rename_again(namespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _old_vault()
    _unlock()
    monkeypatch.setattr(content_cache, "rename_meta_tags_in_tag_bar", lambda _tags: pytest.fail("renamed again"))
    _unlock()
    assert content_cache.get_cached_tags("answer") == "@ai ((@highlight))"


def test_a_restored_older_backup_is_converted_again(namespace) -> None:
    _old_vault()
    _unlock()
    # A backup from before the upgrade: its notes have the old names and no record.
    with begin_writer() as connection:
        connection.execute(f"DELETE FROM {NAMESPACE_CONTENT_MIGRATIONS_TABLE}")
        connection.execute("DELETE FROM notes")
    _store_raw("answer", tags="@llm", proposed_tags="", prev_id=None, next_id=None)
    _unlock()
    assert _stored("answer") == ("@ai", "", _UPDATED_AT.isoformat())
    assert _records() == [(META_TAG_RENAMES_MIGRATION_ID, "complete", 1)]


def test_an_encrypted_vault_stores_the_renamed_tags_encrypted(namespace) -> None:
    set_session_dek(os.urandom(_DEK_BYTES))
    set_encryption_required(True)
    _old_vault()
    _unlock()
    with begin_writer() as connection:
        ciphertext, nonce = connection.execute(
            "SELECT tags, tags_encryption_nonce FROM notes WHERE id = 'answer'",
        ).fetchone()
        state_json = fetch_tab_state_row(connection)["state_json"]
    assert nonce is not None
    assert "@ai" not in ciphertext
    assert "journal" not in state_json
    assert _stored("answer")[0] == "@ai ((@highlight))"


def test_the_new_names_render_as_the_old_ones_did() -> None:
    def view(tags: str) -> str:
        return format_note_content_for_view(content_html="<div>text</div>", tags=tags, redact_credentials=False)

    assert "meta-highlighter" in view("@highlight")
    # Both spellings of gray work, and neither is converted.
    assert view("@gray") == view("@grey")
    assert rename_meta_tags_in_tag_bar("@gray @grey") == "@gray @grey"


def test_the_old_names_are_no_longer_built_in() -> None:
    known = list_known_meta_tag_terms()
    assert not set(meta_tag_renames.META_TAG_RENAMES) & known
    assert set(meta_tag_renames.META_TAG_RENAMES.values()) | {"@gray", "@grey"} <= known
    assert (find_list_style("@bullets"), find_list_style("@numbered")) == ("bulleted", "numbered")
