"""A copied note's diagrams are its own (docs/ui/excalidraw.md, "Copies"; the maintainer,
2026-11-22): a pasted copy of a note gets its own copy of each diagram another note still
shows; a note that was cut goes on with the diagram it had."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.db.file_session import begin_file_writer
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services import diagram_copies
from app.services.diagram_copies import diagram_ids_in, snapshot_with_own_diagrams
from app.services.file_registry import file_registry
from app.services.file_storage import (
    FileNotEditable,
    create_file,
    download_file,
    duplicate_editable_file,
    find_file_preview,
    store_file_previews,
)

SCENE = json.dumps({"type": "excalidraw", "version": 2, "elements": [{"id": "r1", "type": "rectangle"}], "appState": {}, "files": {}}).encode()
LIGHT_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#ffffff"/></svg>'
DARK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#121212"/></svg>'
TOKEN = "token"


@pytest.fixture
def files(tmp_path: Path, monkeypatch):
    set_encryption_required(True)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_session_dek(os.urandom(32))
    file_registry.reset()
    # The in-memory file database is shared for the whole test process; start each test empty.
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM files")
    yield
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)
    SafeSession.use_file_db()


class _Notes:
    """The live notes' texts, by id: who still shows a diagram."""

    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts

    def note_ids_referencing(self, target_ids: set[str]) -> set[str]:
        return {note_id for note_id, text in self.texts.items() if any(target_id in text for target_id in target_ids)}


def _diagram(name: str) -> str:
    record = create_file(original_filename=name, mime_type="application/vnd.excalidraw+json", content_bytes=SCENE, token=TOKEN)
    store_file_previews(
        file_id=record.id, previews_by_variant={"light": LIGHT_SVG, "dark": DARK_SVG},
        content_revision=record.content_revision, token=TOKEN,
    )
    return record.id


def _entry(note_id: str, content: str) -> dict:
    return {"id": note_id, "parent_id": None, "content": content, "tags": "", "proposed_tags": "", "is_collapsed": False}


def test_a_duplicate_is_a_file_of_its_own_with_the_same_drawing_and_previews(files) -> None:
    battle_flow = _diagram("Battle flow.excalidraw")
    copy = duplicate_editable_file(file_id=battle_flow, name="Battle flow.excalidraw", token=TOKEN)
    assert copy.id != battle_flow
    assert copy.title == "Battle flow.excalidraw"
    assert download_file(copy.id, TOKEN).content_bytes == SCENE
    assert find_file_preview(file_id=copy.id, variant="light", token=TOKEN).content_bytes == LIGHT_SVG
    assert find_file_preview(file_id=copy.id, variant="dark", token=TOKEN).content_bytes == DARK_SVG


def test_a_diagram_never_rendered_is_duplicated_without_previews(files) -> None:
    blank = create_file(original_filename="Diagram.excalidraw", mime_type="application/vnd.excalidraw+json", content_bytes=SCENE, token=TOKEN)
    copy = duplicate_editable_file(file_id=blank.id, name="Diagram.excalidraw", token=TOKEN)
    assert find_file_preview(file_id=copy.id, variant="light", token=TOKEN) is None


def test_only_diagrams_are_duplicated(files) -> None:
    pdf = create_file(original_filename="Rules.pdf", mime_type="application/pdf", content_bytes=b"%PDF", token=TOKEN)
    with pytest.raises(FileNotEditable):
        duplicate_editable_file(file_id=pdf.id, name="Rules.pdf", token=TOKEN)


def test_a_pasted_copy_gets_its_own_copy_of_a_diagram_another_note_still_shows(files, monkeypatch) -> None:
    battle_flow = _diagram("Battle flow.excalidraw")
    pdf = create_file(original_filename="Rules.pdf", mime_type="application/pdf", content_bytes=b"%PDF", token=TOKEN)
    # "Combat design" was copied and is still there.
    combat_design = f"<div>Combat design</div><div>![[{battle_flow}]]</div><div>![[{pdf.id}]]</div>"
    monkeypatch.setattr(diagram_copies, "note_store", _Notes({"combat": combat_design}))
    pasted = snapshot_with_own_diagrams([_entry("combat", combat_design)], token=TOKEN)
    (own,) = diagram_ids_in(pasted[0]["content"])
    assert own != battle_flow
    assert file_registry.title_of(own) == "Battle flow.excalidraw"
    assert pasted[0]["content"] == combat_design.replace(battle_flow, own), "the other file is the same file"


def test_a_cut_note_goes_on_with_its_diagram(files, monkeypatch) -> None:
    battle_flow = _diagram("Battle flow.excalidraw")
    combat_design = f"<div>Combat design</div><div>![[{battle_flow}]]</div>"
    # Cut: no live note shows the diagram any more.
    monkeypatch.setattr(diagram_copies, "note_store", _Notes({}))
    pasted = snapshot_with_own_diagrams([_entry("combat", combat_design)], token=TOKEN)
    assert pasted[0]["content"] == combat_design


def test_pasted_notes_that_share_a_diagram_share_its_copy(files, monkeypatch) -> None:
    battle_flow = _diagram("Battle flow.excalidraw")
    texts = {"combat": f"<div>![[{battle_flow}]]</div>", "notes": f"<div>See [[{battle_flow}]]</div>"}
    monkeypatch.setattr(diagram_copies, "note_store", _Notes(texts))
    pasted = snapshot_with_own_diagrams([_entry("combat", texts["combat"]), _entry("notes", texts["notes"])], token=TOKEN)
    assert diagram_ids_in(pasted[0]["content"]) == diagram_ids_in(pasted[1]["content"]) != [battle_flow]
