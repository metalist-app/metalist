from __future__ import annotations

from dataclasses import dataclass
from app.usecases.base import QueryCommand
from app.services.undo_state import redo as do_redo, maybe_reset_on_context, undo_emptied_by_another_view
from app.services.sync import get_current_sync_uuid


@dataclass
class CmdRedo(QueryCommand):
    client_id: str
    token: str
    undo_context: str

    def execute(self):
        maybe_reset_on_context(self.client_id, self.undo_context)
        scroll_restore = do_redo(self.client_id, self.token)
        if scroll_restore is not None:
            return {
                "status": "success",
                "message": "Redo successful",
                "updateUUID": get_current_sync_uuid(),
                "scrollRestore": scroll_restore,
            }
        else:
            return {
                "status": "noop",
                "message": _nothing_to_redo_message(self.client_id),
                # Said only then: an empty redo is otherwise quiet.
                "changedOnAnotherDevice": undo_emptied_by_another_view(self.client_id),
                "updateUUID": get_current_sync_uuid(),
            }


def _nothing_to_redo_message(client_id: str) -> str:
    """Why Redo did nothing: another view's change emptied it too (multi-view editing, 2026-11-14)."""
    if undo_emptied_by_another_view(client_id):
        return "Nothing to redo: notes were changed on another device."
    return "No actions to redo"
