from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.services.content_formatting import is_markdown_note
from app.services.input_errors import InputRejected
from app.services.markdown_tasks import (
    toggle_callout_fold_in_note_html,
    toggle_html_fold_in_note_html,
    toggle_task_in_note_html,
)
from app.services import undo_state
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.usecases.base import QueryCommand
from app.usecases.update_content import apply_update_content


@dataclass
class CmdToggleMarkdownTask(QueryCommand):
    """A click on a task's box in a Markdown note: [ ] becomes [x] or back, one undo step
    (docs/ui/content-formatting.md, Tasks)."""

    note_id: str
    task_index: int
    is_ticked: bool
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, str]:
        record = store.get(self.note_id)
        if not is_markdown_note(record.tags):
            raise InputRejected("This note is no longer Markdown; its boxes are text now.")
        next_content = toggle_task_in_note_html(
            content_html=record.content, task_index=self.task_index, is_ticked=self.is_ticked,
        )
        return _save_click(
            note_id=self.note_id, before=record.content, after=next_content, tags=record.tags, token=self.token,
            client_id=self.client_id, undo_context=self.undo_context, viewport=self.viewport,
        )


@dataclass
class CmdToggleMarkdownCallout(QueryCommand):
    """A click on a folding callout's title in a Markdown note: - becomes + or back, one
    undo step (docs/ui/content-formatting.md, Callouts)."""

    note_id: str
    callout_index: int
    is_open: bool
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, str]:
        record = store.get(self.note_id)
        if not is_markdown_note(record.tags):
            raise InputRejected("This note is no longer Markdown; its callouts are text now.")
        next_content = toggle_callout_fold_in_note_html(
            content_html=record.content, callout_index=self.callout_index, is_open=self.is_open,
        )
        return _save_click(
            note_id=self.note_id, before=record.content, after=next_content, tags=record.tags, token=self.token,
            client_id=self.client_id, undo_context=self.undo_context, viewport=self.viewport,
        )


@dataclass
class CmdToggleMarkdownFold(QueryCommand):
    """A click on the title of a <details> fold written in a Markdown note: its open
    attribute added or removed, one undo step (docs/ui/content-formatting.md, HTML)."""

    note_id: str
    fold_index: int
    is_open: bool
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, str]:
        record = store.get(self.note_id)
        if not is_markdown_note(record.tags):
            raise InputRejected("This note is no longer Markdown; its folds are text now.")
        next_content = toggle_html_fold_in_note_html(
            content_html=record.content, fold_index=self.fold_index, is_open=self.is_open,
        )
        return _save_click(
            note_id=self.note_id, before=record.content, after=next_content, tags=record.tags, token=self.token,
            client_id=self.client_id, undo_context=self.undo_context, viewport=self.viewport,
        )


def _save_click(
    *, note_id: str, before: str, after: str, tags: str, token: str, client_id: str, undo_context: str,
    viewport: Dict[str, object],
) -> Dict[str, str]:
    assert after != before, "a click that writes into a note changes it"
    apply_update_content(note_id, after, tags, token)
    undo_state.record_update(
        client_id,
        undo_context,
        note_id,
        before=before,
        after=after,
        before_tags=tags,
        after_tags=tags,
        viewport=viewport,
    )
    return {"status": "success", "updateUUID": generate_new_uuid()}
