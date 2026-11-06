from __future__ import annotations

import time
from types import SimpleNamespace

from app.services.agent.note_aliases import NoteAliases


def _snapshot(view_ids: tuple[str, ...], tree_ids: tuple[str, ...], selected_ids: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        ordered_note_ids=view_ids,
        tree_nodes_by_id=dict.fromkeys(tree_ids),
        selected_note=SimpleNamespace(reference_note_ids=selected_ids),
    )


def test_aliases_follow_the_view_then_its_trees_then_the_selected_tree() -> None:
    aliases = NoteAliases.from_snapshot(_snapshot(("b", "a"), ("a", "c", "b"), ("d", "c")))

    assert aliases.id_by_alias() == {"n1": "b", "n2": "a", "n3": "c", "n4": "d"}


def test_a_whole_vault_gets_its_aliases_at_once() -> None:
    # 0.26.0, 2026-11-05: an AI question with an empty search box spent minutes here on a large
    # vault, the server answering nothing meanwhile, as each note was looked for in a list.
    note_ids = tuple(f"note-{index}" for index in range(50_000))
    started = time.perf_counter()

    aliases = NoteAliases.from_snapshot(_snapshot(note_ids, note_ids, note_ids[:10]))

    assert time.perf_counter() - started < 1.0
    assert aliases.alias("note-49999") == "n50000"
