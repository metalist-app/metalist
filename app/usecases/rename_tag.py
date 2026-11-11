from __future__ import annotations

from dataclasses import dataclass

from app.db.raw_connection import raw_sqlite_connection
from app.db.session import begin_writer
from app.db.notes_sql import update_note_fields_preserving_updated_at as db_update_note_fields_preserving_updated_at
from app.db.settings_sql import fetch_settings
from app.security.encryption import is_encryption_available, encrypt
from app.services.content_cache import cache_note, cache_note_tags, cache_note_text
from app.services.note_store import store as note_store
from app.services.ontology_rules_store import rename_tag_everywhere
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.security.note_html import sanitize_note_html
from app.services.search_links import has_search_links, rename_tag_in_search, rename_tag_in_search_links
from app.services.tab_state import tab_state_store
from app.services.tag_rename import rename_tag_in_tag_bar
from app.utils.text_utils import strip_html


def apply_rename_tag_everywhere(*, old: str, new: str, token: str) -> dict:
    if not isinstance(old, str) or old.strip() == "":
        raise TypeError('old must be a non-empty string')
    if not isinstance(new, str) or new.strip() == "":
        raise TypeError('new must be a non-empty string')
    if not isinstance(token, str):
        raise TypeError('token must be a string')

    old_tag = old.strip()
    new_tag = new.strip()
    if old_tag == new_tag:
        raise ValueError('old and new must differ')
    if new_tag == 'OR':
        raise ValueError('OR is reserved for search')

    if not note_store.loaded:
        raise RuntimeError('NoteStore must be loaded before renaming tags')

    rename_tag_everywhere(old=old_tag, new=new_tag, token=token)

    updates: list[tuple[str, str, str]] = []
    for note_id in note_store.list_note_ids():
        record = store.get(note_id)
        updated, changed = rename_tag_in_tag_bar(tags=record.tags, old=old_tag, new=new_tag)
        if not changed:
            continue
        updates.append((note_id, record.content, updated))

    # A search link's search names tags too (docs/ready-to-build/search-links.md §6): renamed
    # where it is a term, keeping the note's updated time as the tag bars' rename does.
    content_updates: list[tuple[str, str]] = []
    for note_id in note_store.list_note_ids():
        content = store.get(note_id).content
        if not has_search_links(content):
            continue
        # Cleaned as a save cleans it: stored notes are trusted as cleaned (content_cache.py).
        renamed_content = sanitize_note_html(rename_tag_in_search_links(content, old=old_tag, new=new_tag))
        if renamed_content != content:
            content_updates.append((note_id, renamed_content))

    with begin_writer() as connection:
        settings = fetch_settings(connection)
        encryption_enabled = False
        if settings is not None:
            encryption_enabled = bool(settings["encryption_enabled"])

        if encryption_enabled and not is_encryption_available(token):
            raise RuntimeError('Encryption is enabled but no DEK is available for this token')

        for note_id, _content, tags in updates:
            tags_ciphertext, tags_nonce, tags_tag = encrypt(tags, token)
            if (tags_nonce is None) != (tags_tag is None):
                raise RuntimeError('Encrypted tags must include both nonce and tag')

            db_update_note_fields_preserving_updated_at(
                connection,
                note_id,
                tags=tags_ciphertext,
                tags_encryption_nonce=tags_nonce,
                tags_encryption_tag=tags_tag,
            )

        for note_id, content in content_updates:
            ciphertext, nonce, tag = encrypt(content, token)
            if (nonce is None) != (tag is None):
                raise RuntimeError('Encrypted content must include both nonce and tag')
            db_update_note_fields_preserving_updated_at(
                connection, note_id, content=ciphertext, encryption_nonce=nonce, encryption_tag=tag,
            )
        # And every search context's search: a saved search never names a tag gone.
        renamed_search_count = tab_state_store.rename_search_terms(
            rename=lambda search: rename_tag_in_search(search, old=old_tag, new=new_tag),
            connection=raw_sqlite_connection(connection),
        )

    tag_changes = {}
    for note_id, _content, tags in updates:
        record = note_store.get_note(note_id)
        if record.updated_at is None:
            raise RuntimeError(f"Cannot preserve missing updated_at while renaming tag: {note_id}")
        cache_note_tags(note_id, tags)
        tag_changes[note_id] = (tags, record.proposed_tags)
    # One incremental recompute for every renamed note, not one per note.
    note_store.apply_bulk_tag_sources(tag_changes)
    for note_id, content in content_updates:
        record = store.get(note_id)
        if record.updated_at is None:
            raise RuntimeError(f"Cannot preserve missing updated_at while renaming a tag in search links: {note_id}")
        cache_note(note_id, content)
        cache_note_text(note_id, strip_html(content))
        store.update_note_sources(note_id, content, record.tags, record.proposed_tags, updated_at=record.updated_at)

    update_uuid = generate_new_uuid()
    return {
        'ok': True,
        'renamedNoteCount': len(updates),
        'renamedSearchLinkNoteCount': len(content_updates),
        'renamedSearchCount': renamed_search_count,
        'updateUUID': update_uuid,
    }
