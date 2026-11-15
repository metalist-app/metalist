from __future__ import annotations

from dataclasses import dataclass
from app.usecases.base import QueryCommand
from app.services.undo_state import undo as do_undo, maybe_reset_on_context, undo_emptied_by_another_view, undo_history_limited
from app.services.sync import get_current_sync_uuid


@dataclass
class CmdUndo(QueryCommand):
    client_id: str
    token: str
    undo_context: str

    def execute(self):
        maybe_reset_on_context(self.client_id, self.undo_context)
        scroll_restore = do_undo(self.client_id, self.token)
        if scroll_restore is not None:
            return {
                "status": "success",
                "message": "Undo successful",
                "updateUUID": get_current_sync_uuid(),
                "scrollRestore": scroll_restore,
            }
        else:
            return {
                "status": "noop",
                "message": _nothing_to_undo_message(self.client_id),
                "updateUUID": get_current_sync_uuid(),
            }


def _nothing_to_undo_message(client_id: str) -> str:
    """Why Undo did nothing: another view's change emptied this view's history (multi-view
    editing, 2026-11-14), older history went to stay within memory, or there is none."""
    if undo_emptied_by_another_view(client_id):
        return "Nothing to undo: notes were changed on another device."
    if undo_history_limited(client_id):
        return "Older undo history was discarded to stay within memory limits"
    return "No actions to undo"
