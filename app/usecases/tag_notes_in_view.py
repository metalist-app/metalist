"""Adding a tag to, or removing one from, the notes a view shows (Tag Notes in View…, the
maintainer, 2026-11-11; docs/ui/command-palette.md). Added: to each note the view's search
finds, none under another found one, as Delete Notes (Current View) counts them; the notes
under them carry it through them, as they carry every tag of theirs. Removed: from every note
the view shows from those down, so none shown keeps it in its own tag bar. With no search,
every note. One undo step."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List

from app.services.input_errors import InputRejected
from app.services.search_index import extract_tags_for_search
from app.services.snapshot import ResolvedViewScope
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.services.tag_ontology import is_valid_tag_token
from app.services.tag_rename import delete_tag_from_tag_bar
from app.services.tag_term_matching import tag_term_matches_prefix
from app.services.undo_state import record_tag_sources_batch
from app.usecases.base import QueryCommand
from app.usecases.delete_notes_in_view import notes_to_delete
from app.usecases.tag_proposals import merge_accepted_proposals
from app.usecases.update_content import apply_update_note_sources

_SPACE_RUN = re.compile(r" {2,}")

ADD = "add"
REMOVE = "remove"
TAG_ACTIONS = (ADD, REMOVE)


@dataclass(frozen=True)
class TagChange:
    note_id: str
    before_tags: str
    after_tags: str


def require_plain_tag(tag: str) -> None:
    """One tag, as the tag bar takes it: no spaces, quotes or properties."""
    if not is_valid_tag_token(tag):
        raise InputRejected("Enter one tag, without spaces or quotes.")


def found_note_ids(scope: ResolvedViewScope) -> List[str]:
    """The notes the view finds, none under another found one, in list order: every root note
    with no search."""
    return notes_to_delete(scope).top_note_ids


def shown_from_found_note_ids(scope: ResolvedViewScope) -> List[str]:
    """The found notes and every note the view shows under them, in list order."""
    shown: List[str] = []
    for top_id in found_note_ids(scope):
        stack = [top_id]
        while stack:
            note_id = stack.pop()
            shown.append(note_id)
            children = [child for child in store.children(note_id) if _is_shown(scope, child)]
            stack.extend(reversed(children))
    return shown


def _is_shown(scope: ResolvedViewScope, note_id: str) -> bool:
    """With no search the view shows every note."""
    if not scope.filter_active:
        return True
    return note_id in scope.allowed_note_ids


def tag_changes_in_view(scope: ResolvedViewScope, *, action: str, tag: str) -> List[TagChange]:
    """The notes whose own tag bar adding or removing tag changes, and how."""
    assert action in TAG_ACTIONS, action
    require_plain_tag(tag)
    changes: List[TagChange] = []
    if action == ADD:
        for note_id in found_note_ids(scope):
            before = store.get(note_id).tags
            after = merge_accepted_proposals(before, (tag,))
            if after != before:
                changes.append(TagChange(note_id=note_id, before_tags=before, after_tags=after))
        return changes
    for note_id in shown_from_found_note_ids(scope):
        before = store.get(note_id).tags
        after = without_tag(before, tag)
        if after != before:
            changes.append(TagChange(note_id=note_id, before_tags=before, after_tags=after))
    return changes


def without_tag(tags: str, tag: str) -> str:
    """The tag bar with tag gone, whatever its case (Dinner as dinner, as search finds it)."""
    after = tags
    for spelling in extract_tags_for_search(tags):
        if spelling.casefold() == tag.casefold():
            after, _is_changed = delete_tag_from_tag_bar(tags=after, tag=spelling)
    if after == tags:
        return tags
    # The space the tag stood in goes with it.
    return _SPACE_RUN.sub(" ", after).strip()


def tags_to_remove_in_view(scope: ResolvedViewScope, *, prefix: str, limit: int) -> List[str]:
    """The tags in the own tag bars of the notes Remove would touch, those on most notes first,
    as typed (prefix) so far."""
    assert limit > 0, limit
    counts: Counter[str] = Counter()
    spellings: Dict[str, str] = {}
    for note_id in shown_from_found_note_ids(scope):
        for tag in extract_tags_for_search(store.get(note_id).tags):
            if prefix.strip() != "" and not tag_term_matches_prefix(term=tag, prefix=prefix.strip()):
                continue
            if not is_valid_tag_token(tag):
                continue
            key = tag.casefold()
            counts[key] += 1
            if key not in spellings:
                spellings[key] = tag
    ranked = sorted(counts, key=lambda key: (-counts[key], key))
    return [spellings[key] for key in ranked[:limit]]


@dataclass
class CmdTagNotesInView(QueryCommand):
    """Add or remove the tag, if it still changes the expected_note_count notes the dialog said."""

    scope: ResolvedViewScope
    action: str
    tag: str
    expected_note_count: int
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, object]:
        changes = tag_changes_in_view(self.scope, action=self.action, tag=self.tag)
        if len(changes) != self.expected_note_count:
            raise InputRejected("The notes in this view changed while the dialog was open. Try again.")
        if not changes:
            raise InputRejected("No note in this view changes.")
        for change in changes:
            record = store.get(change.note_id)
            apply_update_note_sources(
                note_id=change.note_id, content=record.content, tags=change.after_tags,
                proposed_tags=record.proposed_tags, token=self.token,
            )
        record_tag_sources_batch(
            self.client_id, self.undo_context, changes[0].note_id,
            changes=[
                {
                    "note_id": change.note_id,
                    "before_tags": change.before_tags, "before_proposed_tags": store.get(change.note_id).proposed_tags,
                    "after_tags": change.after_tags, "after_proposed_tags": store.get(change.note_id).proposed_tags,
                }
                for change in changes
            ],
            viewport=self.viewport,
        )
        return {"changedCount": len(changes), "updateUUID": generate_new_uuid()}
