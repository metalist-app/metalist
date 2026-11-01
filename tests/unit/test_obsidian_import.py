"""The Obsidian import, developer version, slice 1 (PLAN.md): every Markdown file of a vault
becomes a root note at the top of the list, as Markdown, with its folder as a tag, its
frontmatter tags and times, in the order of Obsidian's file list; the vault is only read."""

from __future__ import annotations

import hashlib
import typing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest

import app.api.routes.imports as imports_routes
from app.db.file_session import begin_file_writer
from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services.file_registry import file_registry
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.obsidian_import.notes import PlannedNote, plan_file_note, source_tag_for
from app.services.obsidian_import.sources import IMPORT_SOURCES
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
import app.usecases.import_obsidian_vault as import_module
from app.usecases.import_obsidian_vault import CmdImportObsidianVault, CmdPreviewImport

FIXTURE_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "obsidian-vault"
IMPORTED_AT = datetime(2026, 10, 31, 21, 5, tzinfo=timezone.utc)
SOURCE_TAG = source_tag_for(IMPORTED_AT, "obsidian")
FILE_TIME = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)
# The vault is not encrypted in these tests: any token stores files in plain text.
TOKEN = "token"


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
    vault = read_vault(FIXTURE_VAULT, reads_line_break_setting=True)
    assert [str(file.path) for file in vault.markdown_files] == [
        "1. First steps.md", "Broken frontmatter.md", "Daily/2026/2026-10-30.md", "Empty.md",
        "Home/Notes/Index.md", "Links.md", "Projects/Client A/Plan.md", "Projects/Client B/Notes.md",
        "snake_case_name.md", "Weird [Folder]/Inside.md", "Welcome.md", "Work/Notes/Index.md",
    ]
    assert [str(path) for path in vault.other_files] == [
        "attachments/photo.png", "attachments/report.pdf", "attachments/unused.txt",
    ]
    assert [(entry.path, entry.reason) for entry in vault.skipped] == [
        (".obsidian/", "hidden folder"), (".trash/", "hidden folder"), ("Latin1 note.md", "not UTF-8 text"),
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
    vault = read_vault(tmp_path, reads_line_break_setting=True)
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


def test_block_ids_are_hidden_and_comments_noticed_outside_code() -> None:
    note = planned("Note.md", "Para ^abc-1\n\n^def\n\n```\nkeep ^ghi\n%% in code %%\n```", strict=True)
    assert text_of(note) == "Note\n\nPara\n\n```\nkeep ^ghi\n%% in code %%\n```"
    # Kept whole, the note holds both blocks: links to either reach it.
    assert note.root.anchors == ("^abc-1", "^def")
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
    file_registry.reset()
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM files")
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
    file_registry.reset()


def folder_fingerprint(folder: Path) -> list[tuple[str, str, int]]:
    return sorted(
        (str(path.relative_to(folder)), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in folder.rglob("*") if path.is_file()
    )


def first_line(store: NoteStore, note_id: str) -> str:
    return extract_plain_text_from_note_html(store.get_note(note_id).content).split("\n")[0]


# No import report (the maintainer, 2026-11-01): the files alone, at the top, folders first.
def test_a_vault_comes_in_as_root_notes_at_the_top_folders_first(note_store: NoteStore) -> None:
    before = folder_fingerprint(FIXTURE_VAULT)
    result = CmdImportObsidianVault(source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token=TOKEN, imported_at=IMPORTED_AT).execute()
    roots = note_store.get_children(None)
    assert len(roots) == 12 + 1
    assert roots[-1] == "mine"
    # Daily/, Home/, Projects/Client A/ ... then the files at the top: 1. First steps, ...
    assert [first_line(note_store, note_id) for note_id in roots[0:3]] == ["2026-10-30", "Index", "# Plan"]
    assert first_line(note_store, roots[6]) == "1\\. First steps"
    plan = note_store.get_note(roots[2])
    assert plan.created_at.date().isoformat() in ("2024-02-29", "2024-03-01")
    assert result == {"status": "success", "noteCount": 12, "sourceTag": SOURCE_TAG}
    # The tag the wizard's new search context searches: on every file's note.
    assert all(SOURCE_TAG in note_store.get_note(note_id).tags for note_id in roots[:-1])
    assert folder_fingerprint(FIXTURE_VAULT) == before


# As Obsidian's file list shows them (the maintainer, 2026-11-01): in each folder its
# subfolders first, then its files, each A to Z whatever the case.
def test_files_come_in_folders_first_each_a_to_z(tmp_path: Path, note_store: NoteStore) -> None:
    for path in ["b.md", "A/z.md", "A/B/y.md", "c/x.md", "a.md"]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(Path(path).stem)
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    roots = note_store.get_children(None)[:-1]
    assert [first_line(note_store, note_id) for note_id in roots] == ["y", "z", "x", "a", "b"]


@pytest.mark.parametrize(("folder", "message"), [
    ("relative/path", "Choose the vault's folder"),
    ("/no/such/folder/anywhere", "There is no folder at"),
])
def test_a_folder_that_is_no_vault_is_refused(note_store: NoteStore, folder: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        CmdImportObsidianVault(source="obsidian", folder_path=folder, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token=TOKEN, imported_at=IMPORTED_AT).execute()


def test_a_folder_without_markdown_is_refused(note_store: NoteStore, tmp_path: Path) -> None:
    (tmp_path / "picture.png").write_bytes(b"x")
    with pytest.raises(InputRejected, match="holds no Markdown files"):
        CmdImportObsidianVault(source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, token=TOKEN, imported_at=IMPORTED_AT).execute()
    assert note_store.get_children(None) == ["mine"]


# --- The import routes ------------------------------------------------------

class _Request:
    """No request is read: require_request_auth_token is replaced."""


def test_the_folder_picker_answers_with_the_chosen_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_routes, "require_request_auth_token", lambda request: "token")
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: str(FIXTURE_VAULT))
    body = {"source": "obsidian"}
    # The fixture's Markdown files, its Excalidraw-free top and hidden folders aside.
    assert imports_routes.pick_import_folder(request=_Request(), body=body) == {
        "selected": True, "folderPath": str(FIXTURE_VAULT), "markdownFileCount": 13,
    }
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: None)
    assert imports_routes.pick_import_folder(request=_Request(), body=body) == {
        "selected": False, "folderPath": "", "markdownFileCount": 0,
    }


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
    # A heading note is its text tagged @heading, as MetaList writes headings.
    assert outline(root) == ["Trip", ["@heading"], [
        ["Intro.", ["@bullets"], [["one", [], []], ["two", ["@todo"], []]]],
        ["Closing bold.\nSame paragraph.", [], []],
        ["Second paragraph.", [], []],
        # The heading holds the list and more, so it shows no list numbers of its own.
        ["Day 1", ["@heading"], [
            ["Ferry", [], []],
            ["Museum", [], [["Closed Mondays.", [], []]]],
            ["x = 1", ["@code=python"], []],
            ["x^2", ["@LaTeX"], []],
        ]],
    ]]
    assert root.content_html == "Trip"
    assert root.children[1].content_html == "Closing <strong>bold</strong>.\nSame paragraph."


def test_headings_and_lists_keep_a_run_of_paragraphs_together() -> None:
    root = planned_as("Trip.md", SPLIT_SAMPLE, strict=True, split_mode=SPLIT_HEADINGS_AND_LISTS, content_format=CONTENT_RICH).root
    children = outline(root)[2]
    assert children[1] == ["Closing bold.\nSame paragraph.\n\nSecond paragraph.", [], []]
    assert children[2][2][1] == ["Museum\n\nClosed Mondays.", [], []]


def test_a_list_after_a_heading_tags_it_only_when_the_list_is_all_it_holds() -> None:
    only_list = planned_as("N.md", "## H\n\n- a\n- b", strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    assert outline(only_list.root)[2][0][1] == ["@heading", "@bullets"]
    with_more = planned_as("N.md", "## H\n\n- a\n\n```\ncode\n```", strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    assert outline(with_more.root)[2][0][1] == ["@heading"]


def test_rich_text_keeps_formulas_as_latex_and_footnotes_as_metalist_footnotes() -> None:
    note = planned_as(
        "N.md", "A $x^2$ sum[^1] and ==mark==.\n\n> [!tip] Hint\n> Body\n\n[^1]: Source", strict=True,
        split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
    )
    paragraph, callout = note.root.children
    assert paragraph.content_html == "A (((x^2))) sum{{Source}} and <mark>mark</mark>."
    assert set(paragraph.tags) == {"(((@LaTeX)))", "{{@footnote}}"}
    # A callout is an @quote note, its first line the type and title in bold.
    assert sanitize_note_html(callout.content_html) == "<p><strong>Tip: Hint</strong></p><p>Body</p>"
    assert "@quote" in callout.tags


@pytest.mark.parametrize(("quote", "html"), [
    ("> One line", "One line"),
    ("> Two\\\n> lines", "Two<br>\nlines"),
    ("> [!note] Title\n> Body", "<p><strong>Note: Title</strong></p><p>Body</p>"),
    ("> Holds\n>\n> - a list", "<p>Holds</p><ul><li>a list</li></ul>"),
])
def test_a_quote_of_its_own_is_an_at_quote_note(quote: str, html: str) -> None:
    note = planned_as("N.md", f"Before.\n\n{quote}", strict=True, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    quoted = note.root.children[1]
    assert (sanitize_note_html(quoted.content_html), quoted.tags) == (html, ("@quote",))


def test_a_quote_in_a_note_holding_more_is_a_quote_region() -> None:
    note = planned_as("N.md", "Before.\n\n> [!note] Title\n> Body\n\nAfter.", strict=True, split_mode=SPLIT_NONE, content_format=CONTENT_RICH)
    assert "<p>((<strong>Note: Title</strong></p><p>Body))</p>" in note.root.content_html
    assert "((@quote))" in note.root.tags
    # A quote a region could not hold whole (a list in it) stays a quote as HTML.
    listed = planned_as("N.md", "Before.\n\n> Holds\n>\n> - a list", strict=True, split_mode=SPLIT_NONE, content_format=CONTENT_RICH)
    assert "<blockquote><p>Holds</p><ul><li>a list</li></ul></blockquote>" in listed.root.content_html
    assert "((@quote))" not in listed.root.tags


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
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, token=TOKEN,
        imported_at=IMPORTED_AT,
    ).execute()
    roots = note_store.get_children(None)
    welcome = roots[11]
    assert first_line(note_store, welcome) == "Welcome"
    intro = note_store.get_children(welcome)[0]
    assert len(note_store.get_children(intro)) == 3
    assert result["noteCount"] > 12


def test_the_summary_counts_every_note_the_import_writes(note_store: NoteStore) -> None:
    preview = CmdPreviewImport(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        imported_at=IMPORTED_AT,
    ).execute()
    before = len(note_store.list_note_ids())
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, token=TOKEN,
        imported_at=IMPORTED_AT,
    ).execute()
    # Every note the import wrote (once 38 said, 75 written: a split report the summary missed).
    assert len(note_store.list_note_ids()) - before == preview["noteCount"]


# --- Slice 2: links, embeds and attachments -------------------------------------------------

def imported_tree(store: NoteStore, *, split_mode: str, content_format: str) -> dict[str, str]:
    """Import the fixture vault; each imported note's id by its first line (the first one wins)."""
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=split_mode, content_format=content_format, token=TOKEN,
        imported_at=IMPORTED_AT,
    ).execute()
    ids: dict[str, str] = {}
    stack = list(reversed(store.get_children(None)))
    while stack:
        note_id = stack.pop()
        line = first_line(store, note_id)
        if line not in ids:
            ids[line] = note_id
        stack.extend(reversed(store.get_children(note_id)))
    return ids


def readable(store: NoteStore, note_id: str, ids: dict[str, str]) -> str:
    """note_id's stored HTML with each note id written as its first line, each file id as its name."""
    content = store.get_note(note_id).content
    for line, other_id in ids.items():
        content = content.replace(other_id, f"<{line}>")
    for file_id in file_registry.list_ids():
        content = content.replace(file_id, f"<file {file_registry.title_of(file_id)}>")
    return content


def test_split_links_reach_notes_headings_blocks_and_files(note_store: NoteStore) -> None:
    ids = imported_tree(note_store, split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH)
    links = readable(note_store, note_store.get_children(ids["Links"])[0], ids)
    assert links == (
        "A wiki link to [[<Plan>]], one with its own text: [[<Plan>|the plan]], and one through an alias: [[<Plan>]].<br>\n"
        "A Markdown link to [[<2026-10-30>|the daily note]] and one with spaces: [[<Notes>|Client B]].<br>\n"
        "A heading link: [[<Links target>]] and a block link: [[<A paragraph with a block ID.>]].<br>\n"
        "A link to a missing note: [[Nowhere]]. A link in code stays as written: <code>[[Plan]]</code>.<br>\n"
        "A PDF: [[<file report.pdf>]]."
    )
    embeds = [readable(note_store, child, ids) for child in note_store.get_children(ids["Links"])[1:]]
    assert embeds == ["![[<Notes>]]", "![[<file photo.png>|300]]", "![[<file photo.png>]]"]
    # A link back: Welcome's heading section links to the Links note.
    assert readable(note_store, note_store.get_children(ids["Links target"])[0], ids) == "The heading [[<Links>]] points here."


def test_a_file_kept_whole_links_to_whole_notes(note_store: NoteStore) -> None:
    ids = imported_tree(note_store, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN)
    links = readable(note_store, ids["# Links"], ids)
    assert "A heading link: [[<# Welcome>|Welcome &gt; Links target]] and a block link: [[<# Welcome>]]." in links
    assert "![[<file photo.png>|300]]" in links


def test_only_files_a_note_links_to_are_stored_each_once(note_store: NoteStore) -> None:
    imported_tree(note_store, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN)
    assert sorted(file_registry.title_of(file_id) for file_id in file_registry.list_ids()) == ["photo.png", "report.pdf"]


@pytest.mark.parametrize(("written", "expected"), [
    # From the vault's top, from the file's folder, by the end of a path (the shortest first).
    ("[[Projects/Client A/Plan]]", "Plan"),
    ("[[Plan.md]]", "Plan"),
    ("[x](Plan.md)", "Plan"),
    ("[[Index]]", "Home"),
    ("[[Work/Notes/Index]]", "Work"),
    ("[[Client B/Notes]]", "Notes"),
    ("[[the plan]]", "Plan"),
    # A wiki link in a table writes its | as \\|.
    ("[[Plan\\|text]]", "Plan"),
])
def test_links_find_notes_as_obsidian_does(tmp_path: Path, note_store: NoteStore, written: str, expected: str) -> None:
    for path, text in [
        ("Projects/Client A/Plan.md", "---\naliases: [The Plan]\n---\nPlan"), ("Projects/Client A/Other.md", written),
        ("Projects/Client B/Notes.md", "Notes"), ("Home/Index.md", "Home"), ("Work/Notes/Index.md", "Work"),
    ]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    # Each note's last line is its file's text, which tells the two Index notes apart.
    by_body = {
        extract_plain_text_from_note_html(note_store.get_note(note_id).content).split("\n")[-1]: note_id
        for note_id in note_store.get_children(None)
    }
    linking = [note_id for note_id in note_store.get_children(None) if "[[" in note_store.get_note(note_id).content]
    assert len(linking) == 1
    assert f"[[{by_body[expected]}" in note_store.get_note(linking[0]).content


def test_a_canvas_comes_in_as_a_file_in_a_note_of_its_own(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "Note.md").write_text("Text")
    (tmp_path / "Board.canvas").write_text('{"nodes": [], "edges": []}')
    (tmp_path / "Sketch.excalidraw.md").write_text("# Excalidraw Data")
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    roots = note_store.get_children(None)
    names = {file_id: file_registry.title_of(file_id) for file_id in file_registry.list_ids()}
    contents = [note_store.get_note(note_id).content for note_id in roots[:-1]]
    assert len(contents) == 3
    assert contents[0] == f"![[{next(i for i, n in names.items() if n == 'Board.canvas')}]]"
    assert "Text" in contents[1]
    assert contents[2] == f"![[{next(i for i, n in names.items() if n == 'Sketch.excalidraw.md')}]]"


def test_a_file_too_large_is_left_out_and_its_links_stay_as_written(tmp_path: Path, note_store: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_module, "MAX_ATTACHMENT_BYTES", 2)
    (tmp_path / "Note.md").write_text("See ![[big.png]]")
    (tmp_path / "big.png").write_bytes(b"12345")
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    assert "See ![[big.png]]" in extract_plain_text_from_note_html(note_store.get_note(note_store.get_children(None)[0]).content)
    assert file_registry.list_ids() == set()


# --- Slice 1c: a plain Markdown folder ------------------------------------------------------

def test_a_markdown_folder_comes_in_with_its_own_source(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "Trip.md").write_text("First line\nsecond line\n\n- [x] booked")
    # An Obsidian setting in such a folder is not read: plain Markdown keeps its line breaks.
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{broken")
    CmdImportObsidianVault(
        source="markdown", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    roots = note_store.get_children(None)
    trip = note_store.get_note(roots[0])
    assert extract_plain_text_from_note_html(trip.content) == "Trip\n\nFirst line\nsecond line\n\n- [x] booked"
    assert source_tag_for(IMPORTED_AT, "markdown") in trip.tags
    assert "imported:source=markdown" in source_tag_for(IMPORTED_AT, "markdown")


def test_the_routes_know_every_import_source() -> None:
    assert set(typing.get_args(imports_routes.ImportSourceKey)) == set(IMPORT_SOURCES)


# --- Phase 2: the import wizard's summary, before anything is written ----------------------

def test_the_preview_counts_what_the_import_would_do_and_writes_nothing(note_store: NoteStore) -> None:
    before = folder_fingerprint(FIXTURE_VAULT)
    preview = CmdPreviewImport(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        imported_at=IMPORTED_AT,
    ).execute()
    imported = CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    # Every root note but the list's own note ("mine").
    imported_root_count = len(note_store.get_children(None)) - 1
    assert preview == {
        "fileCount": 12, "noteCount": imported["noteCount"], "rootNoteCount": imported_root_count, "attachmentCount": 2, "folderTagCount": 6,
        "filesWithCommentsCount": 1, "blockIdCount": 1, "calloutCount": 1, "missingLinkCount": 1,
        "unreadableFileCount": 1, "unusedAttachmentCount": 1,
    }
    assert folder_fingerprint(FIXTURE_VAULT) == before


def test_the_preview_writes_no_notes_and_stores_no_files(note_store: NoteStore) -> None:
    CmdPreviewImport(
        source="markdown", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        imported_at=IMPORTED_AT,
    ).execute()
    assert note_store.get_children(None) == ["mine"]
    assert file_registry.list_ids() == set()
