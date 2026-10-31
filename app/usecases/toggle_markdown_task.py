from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.services.content_formatting import is_markdown_note
from app.services.input_errors import InputRejected
from app.services.markdown_tasks import toggle_task_in_note_html
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
        assert next_content != record.content, "a toggled task changes the note"

        apply_update_content(self.note_id, next_content, record.tags, self.token)
        undo_state.record_update(
            self.client_id,
            self.undo_context,
            self.note_id,
            before=record.content,
            after=next_content,
            before_tags=record.tags,
            after_tags=record.tags,
            viewport=self.viewport,
        )
        return {"status": "success", "updateUUID": generate_new_uuid()}
