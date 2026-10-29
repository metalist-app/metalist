from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from app.usecases.base import QueryCommand
from app.services.search_query import SearchClause
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.usecases.move import apply_move, _neighbors, _assert_neighbors
from app.usecases.search_context_tags import search_clauses_matching_note, tags_keeping_moved_note_in_search
from app.usecases.update_content import apply_update_content
from app.services.undo_state import record_move


@dataclass
class CmdOutdent(QueryCommand):
    note_id: str
    search_query: Optional[str]
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, str]:
        record = store.get(self.note_id)
        parent_id = record.parent_id
        if parent_id is None:
            return {"status": "noop"}

        parent = store.get(parent_id)
        grandparent_id = parent.parent_id
        siblings = store.children(grandparent_id)
        if parent.id not in siblings:
            raise RuntimeError(
                "Integrity failure: outdent parent missing from siblings list: "
                f"note_id={self.note_id} parent_id={parent_id} grandparent_id={grandparent_id}"
            )
        parent_index = siblings.index(parent.id)
        dest_prev = parent.id
        dest_next = None
        next_index = parent_index + 1
        if next_index < len(siblings):
            dest_next = siblings[next_index]

        before_parent, before_prev, before_next = _neighbors(self.note_id)
        if not isinstance(record.tags, str):
            raise RuntimeError(f"Note tags must be a string | note_id={self.note_id}")
        if not isinstance(record.content, str):
            raise RuntimeError(f"Note content must be a string | note_id={self.note_id}")
        before_tags = record.tags
        if self.search_query is not None and not isinstance(self.search_query, str):
            raise TypeError(f"search_query must be a string or None, got {type(self.search_query)}")
        clauses_matched_before: tuple[SearchClause, ...] = ()
        if isinstance(self.search_query, str):
            clauses_matched_before = search_clauses_matching_note(self.note_id, self.search_query)

        apply_move(self.note_id, grandparent_id, dest_prev, dest_next)
        _assert_neighbors(self.note_id, grandparent_id, dest_prev, dest_next)

        # It stays in the search it was found by, wherever it lands.
        after_tags = tags_keeping_moved_note_in_search(self.note_id, clauses_matched_before)
        if after_tags != before_tags:
            apply_update_content(self.note_id, record.content, after_tags, self.token)

        record_move(
            self.client_id,
            self.undo_context,
            self.note_id,
            before_parent=before_parent,
            before_prev=before_prev,
            before_next=before_next,
            before_tags=before_tags,
            after_parent=grandparent_id,
            after_prev=dest_prev,
            after_next=dest_next,
            after_tags=after_tags,
            viewport=self.viewport,
        )

        update_uuid = generate_new_uuid()
        return {"status": "moved", "updateUUID": update_uuid}
