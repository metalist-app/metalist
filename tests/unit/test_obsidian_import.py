"""The Obsidian import, developer version, slice 1 (PLAN.md): every Markdown file of a vault
becomes a root note at the top of the list, as Markdown, with its folder as a tag, its
frontmatter tags and times, and a report note first; the vault is only read."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path, PurePosixPath

import pytest
from fastapi import HTTPException

import app.api.routes.imports as imports_routes
from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.obsidian_import.notes import PlannedNote, plan_file_note, source_tag_for
from app.services.obsidian_import.vault import VaultFile, read_vault
from app.services.search_index import SearchIndex, tag_bar_values
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.services.tag_ontology import TagOntology
from app.usecases.import_obsidian_vault import CmdImportObsidianVault

FIXTURE_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "obsidian-vault"
IMPORTED_AT = datetime(2026, 10, 31, 21, 5, tzinfo=timezone.utc)
SOURCE_TAG = source_tag_for(IMPORTED_AT)
FILE_TIME = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)


def planned(path: str, text: str, *, strict: bool) -> PlannedNote:
    vault_file = VaultFile(path=PurePosixPath(path), text=text, created_at=FILE_TIME, modified_at=FILE_TIME)
    return plan_file_note(vault_file, uses_strict_line_breaks=strict, source_tag=SOURCE_TAG)


# --- Reading the vault -------------------------------------------------------------------

def test_the_vault_reads_markdown_files_in_name_order_and_reports_the_rest() -> None:
    vault = read_vault(FIXTURE_VAULT)
    assert [str(file.path) for file in vault.markdown_files] == [
        "1. First steps.md", "Broken frontmatter.md", "Daily/2026/2026-10-30.md", "Empty.md",
        "Home/Notes/Index.md", "Projects/Client A/Plan.md", "Projects/Client B/Notes.md",
        "snake_case_name.md", "Weird [Folder]/Inside.md", "Welcome.md", "Work/Notes/Index.md",
    ]
    assert [(entry.path, entry.reason) for entry in vault.skipped] == [
        (".obsidian/", "hidden folder"), (".trash/", "hidden folder"),
        ("attachments/photo.png", "not a Markdown file"), ("Latin1 note.md", "not UTF-8 text"),
    ]
    assert vault.uses_strict_line_breaks is False
    assert vault.settings_problem == ""


@pytest.mark.parametrize(("settings", "is_strict", "problem"), [
    ('{"strictLineBreaks": true}', True, ""),
    ("{}", False, ""),
    ("{broken", False, ".obsidian/app.json is not valid JSON"),
    ("[1, 2]", False, ".obsidian/app.json holds no settings"),
])
def test_obsidians_line_break_setting_is_read(tmp_path: Path, settings: str, is_strict: bool, problem: str) -> None:
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text(settings)
    (tmp_path / "Note.md").write_text("x")
    vault = read_vault(tmp_path)
    assert (vault.uses_strict_line_breaks, vault.settings_problem) == (is_strict, problem)


# --- Planning each note -------------------------------------------------------------------

@pytest.mark.parametrize(("path", "text", "expected"), [
    # The file name is the first line; a first heading repeating it is that line.
    ("Plan.md", "Body.", "Plan\n\nBody."),
    ("Plan.md", "\n# Plan\n\nBody.", "# Plan\n\nBody."),
    ("Plan.md", "# Other\n\nBody.", "Plan\n\n# Other\n\nBody."),
    ("Empty.md", "", "Empty"),
    # A name that would read as Markdown shows as written.
    ("1. First steps.md", "", "1\\. First steps"),
    ("2) Second.md", "", "2\\) Second"),
    ("snake_case_name.md", "", "snake\\_case\\_name"),
    ("# Hashtag.md", "", "\\# Hashtag"),
])
def test_a_notes_first_line_is_its_file_name(path: str, text: str, expected: str) -> None:
    assert planned(path, text, strict=True).text == expected


@pytest.mark.parametrize(("path", "folder_tag"), [
    ("Note.md", ""),
    ("Projects/Client A/Note.md", "Projects/Client-A"),
    ("Weird [Folder]/Note.md", "Weird-Folder"),
    ("Daily/2026/Note.md", "Daily/2026"),
    ("-Dash first/Note.md", "Dash-first"),
])
def test_a_files_folder_is_one_tag(path: str, folder_tag: str) -> None:
    note = planned(path, "", strict=True)
    assert note.folder_tag == folder_tag
    if folder_tag != "":
        assert note.tags.split(" ")[0] == folder_tag


def test_frontmatter_tags_and_times_come_in_and_other_keys_are_reported() -> None:
    note = planned("Plan.md", (
        "---\ntags: [work, \"client stuff\", \"#planning\", \"@meta\"]\ncreated: 2024-03-01\n"
        "updated: 2024-03-05T10:30:00+00:00\nauthor: Ursula Le Guin\n---\nBody."
    ), strict=True)
    assert note.tags == f"work client-stuff planning meta @markdown {SOURCE_TAG}"
    assert note.created_at.date().isoformat() in ("2024-02-29", "2024-03-01")
    assert note.updated_at == datetime(2024, 3, 5, 10, 30, tzinfo=timezone.utc)
    assert note.text == "Plan\n\nBody."
    assert note.findings.unread_keys == ["author"]
    assert note.findings.renamed_tags == [("client stuff", "client-stuff"), ("@meta", "meta")]


@pytest.mark.parametrize(("frontmatter", "tags"), [
    ("tags: alpha beta, gamma", "alpha beta gamma"),
    ("tag: legacy", "legacy"),
    ("Tags:\n  - Upper", "Upper"),
])
def test_a_tags_string_lists_several_tags(frontmatter: str, tags: str) -> None:
    assert planned("Note.md", f"---\n{frontmatter}\n---\n", strict=True).tags == f"{tags} @markdown {SOURCE_TAG}"


def test_unreadable_frontmatter_is_reported_and_the_body_kept() -> None:
    note = planned("Note.md", "---\ntags: [unclosed\n---\nBody.", strict=True)
    assert note.text == "Note\n\nBody."
    assert note.findings.frontmatter_problem == "frontmatter is not valid YAML, so its properties were left out."
    dated = planned("Note.md", "---\ncreated: yesterday\n---\n", strict=True)
    assert dated.created_at == FILE_TIME
    assert "created: 'yesterday' is not a date" in dated.findings.frontmatter_problem


def test_block_ids_are_removed_and_comments_noticed_outside_code() -> None:
    note = planned("Note.md", "Para ^abc-1\n\n^def\n\n```\nkeep ^ghi\n%% in code %%\n```", strict=True)
    assert note.text == "Note\n\nPara\n\n\n```\nkeep ^ghi\n%% in code %%\n```"
    assert note.findings.block_id_count == 2
    assert note.findings.has_comments is False
    assert planned("Note.md", "A %%hidden%% word", strict=True).findings.has_comments is True


@pytest.mark.parametrize(("body", "expected"), [
    # Inside a paragraph, a list item, a quote: each Return becomes a standard break.
    ("one\ntwo\nthree", "one\\\ntwo\\\nthree"),
    ("- item\n  more\n- next", "- item\\\n  more\n- next"),
    ("> a\n> b", "> a\\\n> b"),
    # Never where a block starts or ends, nor in code, math, tables, headings or callout titles.
    ("para\n- item", "para\n- item"),
    ("para\n# Heading", "para\n# Heading"),
    ("# Heading\npara", "# Heading\npara"),
    ("> [!note] Title\n> body", "> [!note] Title\n> body"),
    ("| a | b |\n|---|---|", "| a | b |\n|---|---|"),
    ("```\na\nb\n```", "```\na\nb\n```"),
    ("$$\na\nb\n$$", "$$\na\nb\n$$"),
    ("ends in two  \nnext", "ends in two  \nnext"),
    ("a quote\n> b", "a quote\n> b"),
])
def test_obsidians_line_breaks_become_standard_breaks(body: str, expected: str) -> None:
    assert planned("N.md", body, strict=False).text == f"N\n\n{expected}"
    assert planned("N.md", body, strict=True).text == f"N\n\n{body}"


def test_the_source_tag_is_a_tag_with_two_values() -> None:
    own_tags, values = tag_bar_values(SOURCE_TAG)
    assert own_tags == {"imported"}
    assert values[("imported", "source")].text == "obsidian"
    assert values[("imported", "at")].text == IMPORTED_AT.astimezone().strftime("%Y-%m-%dT%H:%M")


# --- Importing ----------------------------------------------------------------------------

@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    contents: dict[str, str] = {}
    monkeypatch.setattr(note_store_module, "search_index", SearchIndex())
    monkeypatch.setattr(note_store_module, "get_cached_content", lambda note_id: contents[note_id])
    monkeypatch.setattr(note_store_module, "get_cached_text", lambda note_id: contents[note_id])
    monkeypatch.setattr(note_store_module, "get_cached_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    session = SafeSession()
    insert_note(
        session.connection(), note_id="mine", content="", encryption_nonce=None, encryption_tag=None,
        tags="", tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
        proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None,
        parent_id=None, prev_id=None, next_id=None, is_collapsed=False, created_at=FILE_TIME, updated_at=FILE_TIME,
    )
    session.commit()
    contents["mine"] = "<div>My own note</div>"
    store.load_from_db(session, prefetched_rows=None)
    real_add = store.add_notes_from_db

    def add_with_contents(entries):
        for row, content, _tags, _proposed in entries:
            contents[row.id] = content
        return real_add(entries)

    monkeypatch.setattr(store, "add_notes_from_db", add_with_contents)
    yield store
    session.close()


def folder_fingerprint(folder: Path) -> list[tuple[str, str, int]]:
    return sorted(
        (str(path.relative_to(folder)), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in folder.rglob("*") if path.is_file()
    )


def first_line(store: NoteStore, note_id: str) -> str:
    return extract_plain_text_from_note_html(store.get_note(note_id).content).split("\n")[0]


def test_a_vault_comes_in_as_root_notes_at_the_top_with_the_report_first(note_store: NoteStore) -> None:
    before = folder_fingerprint(FIXTURE_VAULT)
    result = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), token="", imported_at=IMPORTED_AT).execute()
    roots = note_store.get_children(None)
    assert len(roots) == 1 + 11 + 1
    assert roots[0] == result["reportNoteId"]
    assert roots[-1] == "mine"
    assert first_line(note_store, roots[0]).startswith("Import report — Obsidian — obsidian-vault — ")
    assert [first_line(note_store, note_id) for note_id in roots[1:4]] == ["1\\. First steps", "Broken frontmatter", "2026-10-30"]
    plan = note_store.get_note(roots[6])
    assert first_line(note_store, roots[6]) == "# Plan"
    assert plan.created_at.date().isoformat() in ("2024-02-29", "2024-03-01")
    assert result["noteCount"] == 11
    assert folder_fingerprint(FIXTURE_VAULT) == before


def test_the_report_lists_what_was_left_out_and_changed(note_store: NoteStore) -> None:
    result = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), token="", imported_at=IMPORTED_AT).execute()
    report = extract_plain_text_from_note_html(note_store.get_note(result["reportNoteId"]).content)
    for line in [
        "**One-way.**", "- 11 notes, one per Markdown file", "- 6 folder tags.",
        "- `attachments/photo.png`: not a Markdown file", "- `Latin1 note.md`: not UTF-8 text",
        "- `aliases`: in 1 file(s)", "- `author`: in 1 file(s)",
        "- `Broken frontmatter.md`: frontmatter is not valid YAML",
        "- Tag `Projects/Client A` became `Projects/Client-A`.",
        "- `%%comments%%` stay as visible text, in 1 file(s).", "- 1 block IDs (`^abc123`) were removed.",
        "- `Welcome.md`",
    ]:
        assert line in report


def test_importing_the_same_vault_again_says_so(note_store: NoteStore) -> None:
    CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), token="", imported_at=IMPORTED_AT).execute()
    again = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), token="", imported_at=IMPORTED_AT).execute()
    report = extract_plain_text_from_note_html(note_store.get_note(again["reportNoteId"]).content)
    assert "**This vault was imported before:** 1 earlier import report(s)" in report


@pytest.mark.parametrize(("folder", "message"), [
    ("relative/path", "Choose the vault's folder"),
    ("/no/such/folder/anywhere", "There is no folder at"),
])
def test_a_folder_that_is_no_vault_is_refused(note_store: NoteStore, folder: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        CmdImportObsidianVault(folder_path=folder, token="", imported_at=IMPORTED_AT).execute()


def test_a_folder_without_markdown_is_refused(note_store: NoteStore, tmp_path: Path) -> None:
    (tmp_path / "picture.png").write_bytes(b"x")
    with pytest.raises(InputRejected, match="holds no Markdown files"):
        CmdImportObsidianVault(folder_path=str(tmp_path), token="", imported_at=IMPORTED_AT).execute()
    assert note_store.get_children(None) == ["mine"]


# --- The developer version's routes ------------------------------------------------------

class _Request:
    """A request as require_request_auth_token reads it is not needed when the gate refuses."""


def test_the_import_routes_do_not_exist_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_routes, "is_development_environment", lambda: False)
    with pytest.raises(HTTPException) as raised:
        imports_routes.import_obsidian_vault(request=_Request(), body={"folderPath": str(FIXTURE_VAULT)})
    assert raised.value.status_code == HTTPStatus.NOT_FOUND
    with pytest.raises(HTTPException) as raised:
        imports_routes.pick_obsidian_vault_folder(request=_Request())
    assert raised.value.status_code == HTTPStatus.NOT_FOUND


def test_the_folder_picker_answers_with_the_chosen_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_routes, "is_development_environment", lambda: True)
    monkeypatch.setattr(imports_routes, "require_request_auth_token", lambda request: "token")
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: str(FIXTURE_VAULT))
    assert imports_routes.pick_obsidian_vault_folder(request=_Request()) == {
        "selected": True, "folderPath": str(FIXTURE_VAULT),
    }
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: None)
    assert imports_routes.pick_obsidian_vault_folder(request=_Request()) == {"selected": False, "folderPath": ""}
