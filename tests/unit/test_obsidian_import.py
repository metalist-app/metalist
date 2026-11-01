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
from app.security.note_html import sanitize_note_html
from app.services.obsidian_import.tree import (
    CONTENT_MARKDOWN,
    CONTENT_RICH,
    SPLIT_HEADINGS_AND_LISTS,
    SPLIT_NONE,
    SPLIT_PARAGRAPHS,
    NoteNode,
)
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
    """The file kept whole as Markdown (slice 1)."""
    return planned_as(path, text, strict=strict, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN)


def planned_as(path: str, text: str, *, strict: bool, split_mode: str, content_format: str) -> PlannedNote:
    vault_file = VaultFile(path=PurePosixPath(path), text=text, created_at=FILE_TIME, modified_at=FILE_TIME)
    return plan_file_note(
        vault_file, uses_strict_line_breaks=strict, source_tag=SOURCE_TAG, split_mode=split_mode,
        content_format=content_format,
    )


def text_of(note: PlannedNote) -> str:
    return extract_plain_text_from_note_html(note.root.content_html)


def tags_of(note: PlannedNote) -> str:
    return " ".join(note.root.tags)


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
    assert text_of(planned(path, text, strict=True)) == expected


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
        assert note.root.tags[0] == folder_tag


def test_frontmatter_tags_and_times_come_in_and_other_keys_are_reported() -> None:
    note = planned("Plan.md", (
        "---\ntags: [work, \"client stuff\", \"#planning\", \"@meta\"]\ncreated: 2024-03-01\n"
        "updated: 2024-03-05T10:30:00+00:00\nauthor: Ursula Le Guin\n---\nBody."
    ), strict=True)
    assert tags_of(note) == f"work client-stuff planning meta @markdown {SOURCE_TAG}"
    assert note.created_at.date().isoformat() in ("2024-02-29", "2024-03-01")
    assert note.updated_at == datetime(2024, 3, 5, 10, 30, tzinfo=timezone.utc)
    assert text_of(note) == "Plan\n\nBody."
    assert note.findings.unread_keys == ["author"]
    assert note.findings.renamed_tags == [("client stuff", "client-stuff"), ("@meta", "meta")]


@pytest.mark.parametrize(("frontmatter", "tags"), [
    ("tags: alpha beta, gamma", "alpha beta gamma"),
    ("tag: legacy", "legacy"),
    ("Tags:\n  - Upper", "Upper"),
])
def test_a_tags_string_lists_several_tags(frontmatter: str, tags: str) -> None:
    assert tags_of(planned("Note.md", f"---\n{frontmatter}\n---\n", strict=True)) == f"{tags} @markdown {SOURCE_TAG}"


def test_unreadable_frontmatter_is_reported_and_the_body_kept() -> None:
    note = planned("Note.md", "---\ntags: [unclosed\n---\nBody.", strict=True)
    assert text_of(note) == "Note\n\nBody."
    assert note.findings.frontmatter_problem == "frontmatter is not valid YAML, so its properties were left out."
    dated = planned("Note.md", "---\ncreated: yesterday\n---\n", strict=True)
    assert dated.created_at == FILE_TIME
    assert "created: 'yesterday' is not a date" in dated.findings.frontmatter_problem


def test_block_ids_are_removed_and_comments_noticed_outside_code() -> None:
    note = planned("Note.md", "Para ^abc-1\n\n^def\n\n```\nkeep ^ghi\n%% in code %%\n```", strict=True)
    assert text_of(note) == "Note\n\nPara\n\n\n```\nkeep ^ghi\n%% in code %%\n```"
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
    assert text_of(planned("N.md", body, strict=False)) == f"N\n\n{expected}"
    assert text_of(planned("N.md", body, strict=True)) == f"N\n\n{body}"


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
    result = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()
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
    result = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()
    report = extract_plain_text_from_note_html(note_store.get_note(result["reportNoteId"]).content)
    for line in [
        "**One-way.**", "- 11 Markdown files, as 11 notes: each file a note at the top of the list, kept whole, in Markdown.",
        "- 6 folder tags.",
        "- `attachments/photo.png`: not a Markdown file", "- `Latin1 note.md`: not UTF-8 text",
        "- `aliases`: in 1 file(s)", "- `author`: in 1 file(s)",
        "- `Broken frontmatter.md`: frontmatter is not valid YAML",
        "- Tag `Projects/Client A` became `Projects/Client-A`.",
        "- `%%comments%%` stay as visible text, in 1 file(s).", "- 1 block IDs (`^abc123`) were removed.",
        "- `Welcome.md`",
    ]:
        assert line in report


def test_importing_the_same_vault_again_says_so(note_store: NoteStore) -> None:
    CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()
    again = CmdImportObsidianVault(folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()
    report = extract_plain_text_from_note_html(note_store.get_note(again["reportNoteId"]).content)
    assert "**This vault was imported before:** 1 earlier import report(s)" in report


@pytest.mark.parametrize(("folder", "message"), [
    ("relative/path", "Choose the vault's folder"),
    ("/no/such/folder/anywhere", "There is no folder at"),
])
def test_a_folder_that_is_no_vault_is_refused(note_store: NoteStore, folder: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        CmdImportObsidianVault(folder_path=folder, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()


def test_a_folder_without_markdown_is_refused(note_store: NoteStore, tmp_path: Path) -> None:
    (tmp_path / "picture.png").write_bytes(b"x")
    with pytest.raises(InputRejected, match="holds no Markdown files"):
        CmdImportObsidianVault(folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token="", imported_at=IMPORTED_AT).execute()
    assert note_store.get_children(None) == ["mine"]


# --- The developer version's routes ------------------------------------------------------

class _Request:
    """A request as require_request_auth_token reads it is not needed when the gate refuses."""


def test_the_import_routes_do_not_exist_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_routes, "is_development_environment", lambda: False)
    with pytest.raises(HTTPException) as raised:
        imports_routes.import_obsidian_vault(request=_Request(), body={
            "folderPath": str(FIXTURE_VAULT), "splitMode": SPLIT_NONE, "contentFormat": CONTENT_MARKDOWN,
        })
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


# --- Slice 4: split modes and rich text ----------------------------------------------------

SPLIT_SAMPLE = "\n".join([
    "# Trip", "", "Intro.", "", "- one", "- [ ] two", "", "Closing **bold**.", "Same paragraph.", "",
    "Second paragraph.", "", "## Day 1", "", "1. Ferry", "2. Museum", "", "   Closed Mondays.", "",
    "```python", "x = 1", "```", "", "$$", "x^2", "$$", "",
])


def outline(node: NoteNode) -> list:
    text = extract_plain_text_from_note_html(node.content_html).strip()
    own = [tag for tag in node.tags if not tag.startswith("imported")]
    return [text, own, [outline(child) for child in node.children]]


def test_headings_lists_and_paragraphs_each_become_a_note() -> None:
    root = planned_as("Trip.md", SPLIT_SAMPLE, strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH).root
    assert outline(root) == ["Trip", [], [
        ["Intro.", ["@bullets"], [["one", [], []], ["two", ["@todo"], []]]],
        ["Closing bold.\nSame paragraph.", [], []],
        ["Second paragraph.", [], []],
        # The heading holds the list and more, so it shows no list numbers of its own.
        ["Day 1", [], [
            ["Ferry", [], []],
            ["Museum", [], [["Closed Mondays.", [], []]]],
            ["x = 1", ["@code=python"], []],
            ["x^2", ["@LaTeX"], []],
        ]],
    ]]
    assert root.content_html == "<h1>Trip</h1>"
    assert root.children[1].content_html == "Closing <strong>bold</strong>.\nSame paragraph."


def test_headings_and_lists_keep_a_run_of_paragraphs_together() -> None:
    root = planned_as("Trip.md", SPLIT_SAMPLE, strict=True, split_mode=SPLIT_HEADINGS_AND_LISTS, content_format=CONTENT_RICH).root
    children = outline(root)[2]
    assert children[1] == ["Closing bold.\nSame paragraph.\n\nSecond paragraph.", [], []]
    assert children[2][2][1] == ["Museum\n\nClosed Mondays.", [], []]


def test_a_list_after_a_heading_tags_it_only_when_the_list_is_all_it_holds() -> None:
    only_list = planned_as("N.md", "## H\n\n- a\n- b", strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    assert outline(only_list.root)[2][0][1] == ["@bullets"]
    with_more = planned_as("N.md", "## H\n\n- a\n\n```\ncode\n```", strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    assert outline(with_more.root)[2][0][1] == []


def test_rich_text_keeps_formulas_as_latex_and_footnotes_as_metalist_footnotes() -> None:
    note = planned_as(
        "N.md", "A $x^2$ sum[^1] and ==mark==.\n\n> [!tip] Hint\n> Body\n\n[^1]: Source", strict=True,
        split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
    )
    paragraph, callout = note.root.children
    assert paragraph.content_html == "A (((x^2))) sum{{Source}} and <mark>mark</mark>."
    assert set(paragraph.tags) == {"(((@LaTeX)))", "{{@footnote}}"}
    assert sanitize_note_html(callout.content_html) == "<blockquote><p><strong>Tip: Hint</strong></p><p>Body</p></blockquote>"


def test_markdown_notes_keep_their_markdown_and_tasks_are_metalist_tasks() -> None:
    note = planned_as(
        "N.md", "Para with[^1].\n\n- [x] done *it*\n- item *it*\n\n[^1]: Note", strict=True,
        split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_MARKDOWN,
    )
    paragraph = note.root.children[0]
    assert extract_plain_text_from_note_html(paragraph.content_html) == "Para with[^1].\n\n[^1]: Note"
    assert paragraph.tags == ("@markdown", "@bullets")
    task, item = paragraph.children
    assert (task.content_html, task.tags) == ("done <em>it</em>", ("@done",))
    assert (extract_plain_text_from_note_html(item.content_html), item.tags) == ("item *it*", ("@markdown",))


def test_a_file_kept_whole_as_rich_text_is_one_note() -> None:
    note = planned_as("Trip.md", SPLIT_SAMPLE, strict=True, split_mode=SPLIT_NONE, content_format=CONTENT_RICH)
    assert note.root.children == ()
    stored = sanitize_note_html(note.root.content_html)
    assert stored.startswith("<h1>Trip</h1><p>Intro.</p><ul><li>one</li><li>☐ two</li></ul>")
    assert "<pre><code>x = 1</code></pre><div>(((x^2)))</div>" in stored
    assert "(((@LaTeX)))" in note.root.tags


def test_a_split_import_writes_each_files_notes_under_it(note_store: NoteStore) -> None:
    result = CmdImportObsidianVault(
        folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, token="",
        imported_at=IMPORTED_AT,
    ).execute()
    roots = note_store.get_children(None)
    welcome = roots[10]
    assert first_line(note_store, welcome) == "Welcome"
    intro = note_store.get_children(welcome)[0]
    assert len(note_store.get_children(intro)) == 3
    assert result["noteCount"] > 11


def test_the_report_comes_in_split_as_the_vault_does(note_store: NoteStore) -> None:
    result = CmdImportObsidianVault(
        folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, token="",
        imported_at=IMPORTED_AT,
    ).execute()
    sections = [first_line(note_store, note_id) for note_id in note_store.get_children(result["reportNoteId"])]
    assert "Imported" in sections and "Left out" in sections and "Files" in sections
