"""The Obsidian import, developer version, slice 1 (PLAN.md): every Markdown file of a vault
becomes a root note at the top of the list, as Markdown, with its folder as a tag, its
frontmatter tags and times, in the order of Obsidian's file list; the vault is only read."""

from __future__ import annotations

import zipfile

import app.services.content_cache as content_cache
from app.utils.text_utils import strip_html

import hashlib
import re
from io import BytesIO
import typing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest
from PIL import Image

import app.api.routes.imports as imports_routes
import app.services.obsidian_import.file_groups as file_groups_module
import app.services.virtual_folders as virtual_folders_module
from app.db.file_session import begin_file_writer
from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services.image_compression import ImageChoice
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services import file_storage
from app.services.file_registry import file_registry
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.obsidian_import.file_groups import group_of
from app.services.obsidian_import.notes import PlannedNote, import_folder_prefix, plan_file_note, source_tag_for
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
from app.services.obsidian_import.import_folder import DiskFolder
from app.services.obsidian_import.vault import VaultFile, read_vault
from app.services.search_index import SearchIndex, tag_bar_values
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.services.tag_ontology import TagOntology
import app.usecases.import_obsidian_vault as import_module
from app.services.file_storage import DownloadedFile
from app.usecases.import_obsidian_vault import (
    CmdEstimateImportImages,
    CmdImportFolderOfFiles,
    CmdImportObsidianVault,
    CmdPreviewFolderOfFiles,
    CmdPreviewImport,
    FileSelection,
    drop_context_tags,
)

FIXTURE_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "obsidian-vault"
IMPORTED_AT = datetime(2026, 10, 31, 21, 5, tzinfo=timezone.utc)
SOURCE_TAG = source_tag_for(IMPORTED_AT, "obsidian")
FILE_TIME = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)
# The vault is not encrypted in these tests: any token stores files in plain text.
TOKEN = "token"
# Images as they are (the Images screen's first choice).
KEEP_ORIGINALS = ImageChoice(compresses=False, longest_side_px=2560)


def planned(path: str, text: str, *, strict: bool) -> PlannedNote:
    """The file kept whole as Markdown (slice 1)."""
    return planned_as(path, text, strict=strict, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN)


def planned_as(path: str, text: str, *, strict: bool, split_mode: str, content_format: str) -> PlannedNote:
    vault_file = VaultFile(path=PurePosixPath(path), text=text, created_at=FILE_TIME, modified_at=FILE_TIME)
    return plan_file_note(
        vault_file, uses_strict_line_breaks=strict, source_tag=SOURCE_TAG, split_mode=split_mode,
        content_format=content_format, folder_prefix="",
    )


def text_of(note: PlannedNote) -> str:
    return extract_plain_text_from_note_html(note.root.content_html)


def tags_of(note: PlannedNote) -> str:
    return " ".join(note.root.tags)


# --- Reading the vault -------------------------------------------------------------------

def test_the_vault_reads_markdown_files_in_name_order_and_reports_the_rest() -> None:
    vault = read_vault(DiskFolder(FIXTURE_VAULT), reads_line_break_setting=True)
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
    vault = read_vault(DiskFolder(tmp_path), reads_line_break_setting=True)
    assert (vault.uses_strict_line_breaks, vault.settings_problem) == (is_strict, problem)


# --- Planning each note -------------------------------------------------------------------

@pytest.mark.parametrize(("path", "text", "expected"), [
    # The file name is the first line, as a heading over a whole file (the maintainer,
    # 2026-11-01); a first heading repeating it is that line.
    ("Plan.md", "Body.", "# Plan\n\nBody."),
    ("Plan.md", "\n# Plan\n\nBody.", "# Plan\n\nBody."),
    ("Plan.md", "# Other\n\nBody.", "# Plan\n\n# Other\n\nBody."),
    ("Empty.md", "", "# Empty"),
    # A name that would read as Markdown shows as written.
    ("1. First steps.md", "", "# 1\\. First steps"),
    ("2) Second.md", "", "# 2\\) Second"),
    ("snake_case_name.md", "", "# snake\\_case\\_name"),
    ("# Hashtag.md", "", "# \\# Hashtag"),
])
def test_a_notes_first_line_is_its_file_name(path: str, text: str, expected: str) -> None:
    assert text_of(planned(path, text, strict=True)) == expected


# A folder tag ends in `/`, which makes it a folder (docs/ready-to-build/virtual-folders.md §1).
@pytest.mark.parametrize(("path", "folder_tag"), [
    ("Note.md", ""),
    ("Projects/Client A/Note.md", "Projects/Client-A/"),
    ("Weird [Folder]/Note.md", "Weird-Folder/"),
    ("Daily/2026/Note.md", "Daily/2026/"),
    ("-Dash first/Note.md", "Dash-first/"),
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
    assert text_of(note) == "# Plan\n\nBody."
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
    assert text_of(note) == "# Note\n\nBody."
    assert note.findings.frontmatter_problem == "frontmatter is not valid YAML, so its properties were left out."
    dated = planned("Note.md", "---\ncreated: yesterday\n---\n", strict=True)
    assert dated.created_at == FILE_TIME
    assert "created: 'yesterday' is not a date" in dated.findings.frontmatter_problem


def test_block_ids_are_hidden_and_comments_noticed_outside_code() -> None:
    note = planned("Note.md", "Para ^abc-1\n\n^def\n\n```\nkeep ^ghi\n%% in code %%\n```", strict=True)
    assert text_of(note) == "# Note\n\nPara\n\n```\nkeep ^ghi\n%% in code %%\n```"
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
    assert text_of(planned("N.md", body, strict=False)) == f"# N\n\n{expected}"
    assert text_of(planned("N.md", body, strict=True)) == f"# N\n\n{body}"


def test_the_source_tag_is_a_tag_with_two_values() -> None:
    own_tags, values = tag_bar_values(SOURCE_TAG)
    assert own_tags == {"imported"}
    assert values[("imported", "source")].text == "obsidian"
    assert values[("imported", "at")].text == IMPORTED_AT.astimezone().strftime("%Y-%m-%dT%H:%M")


# --- Importing ----------------------------------------------------------------------------

@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    contents: dict[str, str] = {}
    index = SearchIndex()
    monkeypatch.setattr(note_store_module, "search_index", index)
    # Whether an import's folder exists is read from the folders' tags in the same index.
    monkeypatch.setattr(virtual_folders_module, "search_index", index)
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


def imported_roots(store: NoteStore) -> list[str]:
    """The import's root notes in their order: every root note but the vault's own "mine",
    after it."""
    return [note_id for note_id in store.get_children(None) if note_id != "mine"]


def first_line(store: NoteStore, note_id: str) -> str:
    """A note's first line as its title: a heading's marks left out (a whole file's name is a
    heading over its text)."""
    line = extract_plain_text_from_note_html(store.get_note(note_id).content).split("\n")[0]
    return re.sub(r"^#{1,6}\s+", "", line)


# No import report (the maintainer, 2026-11-01): the files alone, folders first. After the notes
# already there (the maintainer, 2026-11-07): at the top they looked as if they had replaced
# everything to someone who works without a search.
def test_a_vault_comes_in_as_root_notes_after_the_last_one_folders_first(note_store: NoteStore) -> None:
    before = folder_fingerprint(FIXTURE_VAULT)
    result = CmdImportObsidianVault(source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="").execute()
    roots = note_store.get_children(None)
    assert len(roots) == 1 + 12
    assert roots[0] == "mine"
    # Daily/, Home/, Projects/Client A/ ... then the files at the top: 1. First steps, ...
    assert [first_line(note_store, note_id) for note_id in roots[1:4]] == ["2026-10-30", "Index", "Plan"]
    assert first_line(note_store, roots[7]) == "1\\. First steps"
    plan = note_store.get_note(roots[3])
    assert plan.created_at.date().isoformat() in ("2024-02-29", "2024-03-01")
    # firstRootId: a drop's view brings the import's first note into sight.
    assert result == {"status": "success", "noteCount": 12, "sourceTag": SOURCE_TAG, "firstRootId": roots[1], "prefixFolder": "", "isNewFolder": False}
    # The tag the wizard's new search context searches: on every file's note.
    assert all(SOURCE_TAG in note_store.get_note(note_id).tags for note_id in roots[1:])
    assert folder_fingerprint(FIXTURE_VAULT) == before


# As Obsidian's file list shows them (the maintainer, 2026-11-01): in each folder its
# subfolders first, then its files, each A to Z whatever the case.
def test_files_come_in_folders_first_each_a_to_z(tmp_path: Path, note_store: NoteStore) -> None:
    for path in ["b.md", "A/z.md", "A/B/y.md", "c/x.md", "a.md"]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(Path(path).stem)
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    roots = note_store.get_children(None)
    assert roots[0] == "mine"
    assert [first_line(note_store, note_id) for note_id in roots[1:]] == ["y", "z", "x", "a", "b"]


# Anything imported goes to the bottom, a single note too: one rule to reason about (the
# maintainer, 2026-11-08).
def test_an_import_of_one_note_comes_in_after_the_last_one(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "only.md").write_text("only")
    _import_folder(str(tmp_path))
    roots = note_store.get_children(None)
    assert [roots[0], first_line(note_store, roots[1])] == ["mine", "only"]


def _import_folder(folder: str) -> None:
    CmdImportObsidianVault(source="obsidian", folder_path=folder, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="").execute()


def test_a_relative_folder_is_refused(note_store: NoteStore) -> None:
    with pytest.raises(InputRejected, match="Choose the vault's folder"):
        _import_folder("relative/path")


def test_a_folder_that_is_not_there_is_refused(note_store: NoteStore, tmp_path: Path) -> None:
    # An absolute path on this system: on Windows one starts with its drive, so a path from
    # the root such as /no/such/folder is relative there.
    with pytest.raises(InputRejected, match="There is no folder at"):
        _import_folder(str(tmp_path / "no" / "such" / "folder"))


def test_a_folder_without_markdown_is_refused(note_store: NoteStore, tmp_path: Path) -> None:
    (tmp_path / "picture.png").write_bytes(b"x")
    with pytest.raises(InputRejected, match="holds no Markdown files"):
        CmdImportObsidianVault(source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="").execute()
    assert note_store.get_children(None) == ["mine"]


# --- The import routes ------------------------------------------------------

class _Request:
    """No request is read: require_request_auth_token is replaced."""


def test_the_folder_picker_answers_with_the_chosen_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_routes, "require_request_auth_token", lambda request: "token")
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: str(FIXTURE_VAULT))
    body = {"source": "obsidian"}
    # The fixture's Markdown files, its Excalidraw-free top and hidden folders aside, and its
    # one image compression would shrink (the Images screen shows).
    assert imports_routes.pick_import_folder(request=_Request(), body=body) == {
        "selected": True, "folderPath": str(FIXTURE_VAULT), "fileCount": 13, "imageCount": 1,
    }
    monkeypatch.setattr(imports_routes, "pick_folder", lambda *, prompt: None)
    assert imports_routes.pick_import_folder(request=_Request(), body=body) == {
        "selected": False, "folderPath": "", "fileCount": 0, "imageCount": 0,
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
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    roots = note_store.get_children(None)
    welcome = roots[12]
    assert first_line(note_store, welcome) == "Welcome"
    intro = note_store.get_children(welcome)[0]
    assert len(note_store.get_children(intro)) == 3
    assert result["noteCount"] > 12


def test_the_summary_counts_every_note_the_import_writes(note_store: NoteStore) -> None:
    preview = CmdPreviewImport(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    before = len(note_store.list_note_ids())
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    # Every note the import wrote (once 38 said, 75 written: a split report the summary missed).
    assert len(note_store.list_note_ids()) - before == preview["noteCount"]


# Restored notes (an import, an undone delete: apply_restore_records) are in the content
# caches as a new note is (2026-11-01: renaming a tag after an import failed with "Cache
# missing raw text" on every imported note).
def test_imported_notes_are_in_the_content_caches(note_store: NoteStore) -> None:
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    for note_id in note_store.list_note_ids():
        if note_id == "mine":
            continue
        record = note_store.get_note(note_id)
        assert content_cache.get_cached_text(note_id) == strip_html(record.content)
        assert content_cache.get_cached_tags(note_id) == record.tags
        assert content_cache.get_cached_proposed_tags(note_id) == record.proposed_tags


# --- Slice 2: links, embeds and attachments -------------------------------------------------

def imported_tree(store: NoteStore, *, split_mode: str, content_format: str) -> dict[str, str]:
    """Import the fixture vault; each imported note's id by its first line (the first one wins)."""
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=split_mode, content_format=content_format, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="",
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
    links = readable(note_store, ids["Links"], ids)
    assert "A heading link: [[<Welcome>|Welcome &gt; Links target]] and a block link: [[<Welcome>]]." in links
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
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
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
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    roots = note_store.get_children(None)
    names = {file_id: file_registry.title_of(file_id) for file_id in file_registry.list_ids()}
    contents = [note_store.get_note(note_id).content for note_id in imported_roots(note_store)]
    assert len(contents) == 3
    assert contents[0] == f"![[{next(i for i, n in names.items() if n == 'Board.canvas')}]]"
    assert "Text" in contents[1]
    assert contents[2] == f"![[{next(i for i, n in names.items() if n == 'Sketch.excalidraw.md')}]]"


def test_a_file_too_large_to_hold_in_memory_still_comes_in(tmp_path: Path, note_store: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_module, "MAX_IN_MEMORY_FILE_BYTES", 2)
    (tmp_path / "Note.md").write_text("See ![[big.png]]")
    (tmp_path / "big.png").write_bytes(b"12345")
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_RICH, folder_prefix="", add_to_existing=False,
        images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    file_ids = file_registry.list_ids()
    assert len(file_ids) == 1
    assert file_storage.download_file(next(iter(file_ids)), TOKEN).content_bytes == b"12345"


# --- Slice 1c: a plain Markdown folder ------------------------------------------------------

def test_a_markdown_folder_comes_in_with_its_own_source(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "Trip.md").write_text("First line\nsecond line\n\n- [x] booked")
    # An Obsidian setting in such a folder is not read: plain Markdown keeps its line breaks.
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{broken")
    CmdImportObsidianVault(
        source="markdown", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    trip = note_store.get_note(imported_roots(note_store)[0])
    assert extract_plain_text_from_note_html(trip.content) == "# Trip\n\nFirst line\nsecond line\n\n- [x] booked"
    assert source_tag_for(IMPORTED_AT, "markdown") in trip.tags
    assert "imported:source=markdown" in source_tag_for(IMPORTED_AT, "markdown")


def test_the_routes_know_every_import_source() -> None:
    assert set(typing.get_args(imports_routes.ImportSourceKey)) == set(IMPORT_SOURCES)


# --- Phase 2: the import wizard's summary, before anything is written ----------------------

def test_the_preview_counts_what_the_import_would_do_and_writes_nothing(note_store: NoteStore) -> None:
    before = folder_fingerprint(FIXTURE_VAULT)
    preview = CmdPreviewImport(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    imported = CmdImportObsidianVault(
        source="obsidian", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_PARAGRAPHS, content_format=CONTENT_RICH,
        folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    # Every root note but the list's own note ("mine").
    imported_root_count = len(note_store.get_children(None)) - 1
    assert preview == {
        "prefixFolder": "", "fileCount": 12, "noteCount": imported["noteCount"], "rootNoteCount": imported_root_count,
        "textFileCount": 12, "keptFileCount": imported_root_count - 12, "attachmentCount": 2, "folderTagCount": 6,
        "filesWithCommentsCount": 1, "blockIdCount": 1, "calloutCount": 1, "missingLinkCount": 1,
        "unreadableFileCount": 1, "unusedAttachmentCount": 1,
    }
    assert folder_fingerprint(FIXTURE_VAULT) == before


def test_the_preview_writes_no_notes_and_stores_no_files(note_store: NoteStore) -> None:
    CmdPreviewImport(
        source="markdown", folder_path=str(FIXTURE_VAULT), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    assert note_store.get_children(None) == ["mine"]
    assert file_registry.list_ids() == set()



# --- The folder an import goes into (docs/ready-to-build/import-prefix-folder.md) ----------

@pytest.mark.parametrize(("typed", "folder"), [
    ("My Vault", "My-Vault/"),
    ("Imports/Obsidian", "Imports/Obsidian/"),
    ("Imports\\Old notes/", "Imports/Old-notes/"),
    ("/Imports//Obsidian/", "Imports/Obsidian/"),
    ("", ""),
    ("   ", ""),
])
def test_the_typed_folder_is_cleaned_part_by_part_as_folder_names_are(typed: str, folder: str) -> None:
    assert import_folder_prefix(typed) == folder


def test_a_folder_name_with_nothing_a_tag_can_hold_is_refused() -> None:
    with pytest.raises(InputRejected, match="nothing a folder name can use"):
        import_folder_prefix("@@@")


def _import_into(tmp_path: Path, prefix: str, *, add_to_existing: bool) -> None:
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix=prefix, add_to_existing=add_to_existing, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()


def _folder_tags_by_first_line(store: NoteStore) -> dict[str, list[str]]:
    return {
        first_line(store, note_id): [tag for tag in store.get_note(note_id).tags.split() if tag.endswith("/")]
        for note_id in store.get_children(None)
    }


def test_every_folder_tag_starts_with_the_import_folder_top_level_files_included(tmp_path: Path, note_store: NoteStore) -> None:
    for path in ["top.md", "Projects/Client A/plan.md"]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(Path(path).stem)
    _import_into(tmp_path, "My Vault", add_to_existing=False)
    tags = _folder_tags_by_first_line(note_store)
    assert tags["top"] == ["My-Vault/"]
    assert tags["plan"] == ["My-Vault/Projects/Client-A/"]


def test_a_blank_import_folder_imports_as_before(tmp_path: Path, note_store: NoteStore) -> None:
    for path in ["top.md", "Projects/plan.md"]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(Path(path).stem)
    _import_into(tmp_path, "", add_to_existing=False)
    tags = _folder_tags_by_first_line(note_store)
    assert tags["top"] == []
    assert tags["plan"] == ["Projects/"]


def test_an_existing_import_folder_is_added_to_only_when_asked(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "top.md").write_text("top")
    _import_into(tmp_path, "My Vault", add_to_existing=False)
    with pytest.raises(InputRejected, match="already exists"):
        _import_into(tmp_path, "my vault", add_to_existing=False)
    _import_into(tmp_path, "My Vault", add_to_existing=True)
    assert [tags for line, tags in _folder_tags_by_first_line(note_store).items() if line == "top"] == [["My-Vault/"]]
    assert sum(1 for note_id in note_store.get_children(None) if first_line(note_store, note_id) == "top") == 2


def _import_files_into(folder: Path, prefix: str) -> dict[str, object]:
    return CmdImportFolderOfFiles(
        folder_path=str(folder), selection=_selection([], excluded_files=(), included_files=()), split_mode=SPLIT_NONE,
        content_format=CONTENT_MARKDOWN, folder_prefix=prefix, add_to_existing=True, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()


# A drop lands on the folder it made; one that already held notes shows old and new together.
def test_a_folder_of_files_says_whether_it_made_a_new_folder(tmp_path: Path, note_store: NoteStore) -> None:
    (tmp_path / "top.md").write_text("top")
    first = _import_files_into(tmp_path, "Big Files")
    again = _import_files_into(tmp_path, "Big Files")
    in_no_folder = _import_files_into(tmp_path, "")
    assert (first["isNewFolder"], first["prefixFolder"]) == (True, "Big-Files/")
    assert (again["isNewFolder"], again["prefixFolder"]) == (False, "Big-Files/")
    assert (in_no_folder["isNewFolder"], in_no_folder["prefixFolder"]) == (False, "")


# Each import's search finds its own notes: a note carrying a second import's tag (dropped while
# viewing that import's search) has two values for the property, and is found by neither.
def test_a_drop_in_an_earlier_imports_search_does_not_take_its_tag(note_store: NoteStore) -> None:
    earlier = "imported:source=files:at=2020-01-02T03:04"
    assert drop_context_tags(search=earlier, folder_filter="", folder_prefix="Big Files") == ""
    assert drop_context_tags(search=f"{earlier} @todo", folder_filter="", folder_prefix="Big Files") == "@todo"


# --- A folder of any files (docs/ready-to-build/folder-import-and-file-previews.md) ---------

@pytest.mark.parametrize(("path", "group"), [
    ("notes.md", "text"),
    ("Sub/readme.TXT", "text"),
    ("photo.JPG", "images"),
    ("Papers/report.pdf", "pdf"),
    ("letter.docx", "documents"),
    (".DS_Store", "hidden"),
    (".git/config", "hidden"),
    ("Docs/~$Report.docx", "hidden"),
    ("Thumbs.db", "hidden"),
    ("app/node_modules/left-pad/index.js", "dependencies"),
    ("app/dist/bundle.js", "build"),
    ("app/main.pyc", "build"),
    ("app/main.py", "code"),
    ("mystery.xyz", "other"),
])
def test_each_file_is_in_one_checklist_group(path: str, group: str) -> None:
    assert group_of(PurePosixPath(path)).key == group


def _selection(excluded_groups: list[str], *, excluded_files: tuple[str, ...], included_files: tuple[str, ...]) -> FileSelection:
    return FileSelection(
        excluded_groups=tuple(excluded_groups), excluded_files=excluded_files, included_files=included_files,
        keeps_markdown_as_files=False,
    )


def _shown_as(store: NoteStore, note_id: str) -> str:
    """A note by what it shows: the name of the file it holds alone, else its first line."""
    files = file_registry.referenced_file_names(strip_html(store.get_note(note_id).content))
    if len(files) == 1:
        return files[0][1]
    return first_line(store, note_id)


def _write_files(folder: Path, files: dict[str, bytes]) -> None:
    for relative, content in files.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_bytes(content)


def test_the_checklist_groups_files_largest_first(tmp_path: Path) -> None:
    _write_files(tmp_path, {
        "a.md": b"x" * 10, "b.png": b"x" * 50, "c.png": b"x" * 150, "node_modules/d.js": b"x" * 30,
    })
    groups = file_groups_module.file_groups(file_groups_module.folder_files(DiskFolder(tmp_path)))
    assert [(group.kind.key, group.file_count, group.total_bytes) for group in groups] == [
        ("images", 2, 200), ("dependencies", 1, 30), ("text", 1, 10),
    ]
    assert [group.kind.is_skipped_by_default for group in groups] == [False, True, False]
    # Each kind's files, the largest first.
    assert [str(folder_file.path) for folder_file in groups[0].files] == ["c.png", "b.png"]


def test_a_folder_of_files_comes_in_every_file_a_note_the_unticked_left_out(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {
        "notes.md": b"# Notes\nSome text", "plain.txt": b"Plain text", "photo.png": b"\x89PNG fake",
        "Sub/report.pdf": b"%PDF fake", ".DS_Store": b"junk", "node_modules/x.js": b"junk",
    })
    result = CmdImportFolderOfFiles(
        folder_path=str(tmp_path), selection=_selection(["hidden", "dependencies", "build"], excluded_files=(), included_files=()), split_mode=SPLIT_NONE,
        content_format=CONTENT_MARKDOWN, folder_prefix="Stuff", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    assert result["noteCount"] == 4
    roots = imported_roots(note_store)
    lines = {_shown_as(note_store, note_id): note_store.get_note(note_id) for note_id in roots}
    assert set(lines) == {"Notes", "plain", "photo.png", "report.pdf"}
    # A file's note: the file alone, no line with its name over it (its card shows the name).
    assert re.fullmatch(r"!\[\[[0-9a-f-]{36}\]\]", strip_html(lines["report.pdf"].content).strip())
    assert "Stuff/Sub/" in lines["report.pdf"].tags.split()
    assert "Stuff/" in lines["photo.png"].tags.split()
    assert all(tag.startswith("imported:source=files") for tag in [
        next(tag for tag in note.tags.split() if tag.startswith("imported:")) for note in lines.values()
    ])


def test_nothing_ticked_is_refused(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {".DS_Store": b"junk"})
    with pytest.raises(InputRejected, match="tick at least one kind"):
        CmdImportFolderOfFiles(
            folder_path=str(tmp_path), selection=_selection(["hidden"], excluded_files=(), included_files=()), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
            folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
        ).execute()


# Files ticked against their kind (the maintainer, 2026-11-01): one left out of a ticked kind,
# one brought in from an unticked kind.
def test_single_files_can_be_ticked_against_their_kind(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {
        "keep.png": b"\x89PNG", "skip.png": b"\x89PNG", ".config/wanted.txt": b"wanted", ".config/junk.txt": b"junk",
    })
    CmdImportFolderOfFiles(
        folder_path=str(tmp_path),
        selection=_selection(["hidden"], excluded_files=("skip.png",), included_files=(".config/wanted.txt",)),
        split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    lines = {_shown_as(note_store, note_id) for note_id in imported_roots(note_store)}
    assert lines == {"keep.png", "wanted"}


def test_a_ticked_file_no_longer_in_the_folder_is_refused(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {"keep.png": b"\x89PNG"})
    with pytest.raises(InputRejected, match="no longer in the folder"):
        CmdImportFolderOfFiles(
            folder_path=str(tmp_path), selection=_selection([], excluded_files=("gone.png",), included_files=()), split_mode=SPLIT_NONE,
            content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
        ).execute()



# One choice for all Markdown files (the maintainer, 2026-11-01): kept as files, each is a note
# holding just the file, as a PDF is; a .txt file still comes in with its text.
def test_markdown_files_can_be_kept_as_files(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {"README.md": b"# Readme\nHello", "notes.txt": b"Plain text"})
    selection = FileSelection(excluded_groups=(), excluded_files=(), included_files=(), keeps_markdown_as_files=True)
    CmdImportFolderOfFiles(
        folder_path=str(tmp_path), selection=selection, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    roots = imported_roots(note_store)
    assert {_shown_as(note_store, note_id) for note_id in roots} == {"README.md", "notes"}
    readme = next(note_id for note_id in roots if _shown_as(note_store, note_id) == "README.md")
    assert re.fullmatch(r"!\[\[[0-9a-f-]{36}\]\]", strip_html(note_store.get_note(readme).content).strip())


# Split, a file's top note holds just its name: drawn as a heading (the maintainer,
# 2026-11-01), whether the name was added or is the file's own first heading (a heading
# note as every heading is when split).
@pytest.mark.parametrize("text", ["Body.\n\n## Part\n\nMore.", "# Plan\n\nBody."])
@pytest.mark.parametrize("split_mode", [SPLIT_HEADINGS_AND_LISTS, SPLIT_PARAGRAPHS])
def test_a_split_files_top_note_is_a_heading_note(text: str, split_mode: str) -> None:
    note = planned_as("Plan.md", text, strict=True, split_mode=split_mode, content_format=CONTENT_RICH)
    assert note.root.tags.count("@heading") == 1


def test_a_whole_file_is_no_heading_note() -> None:
    assert "@heading" not in planned("Plan.md", "Body.", strict=True).root.tags


# Images compressed (folder-import-and-file-previews.md, Images compressed; the maintainer,
# 2026-11-01): acceptance checks (3), (4) and (9) through the import.
PHOTO_SIZE = (4000, 3000)
NOISE_SIGMA = 40
PHOTO_QUALITY = 95


def _photo_bytes() -> bytes:
    picture = Image.merge("RGB", [Image.effect_noise(PHOTO_SIZE, NOISE_SIGMA) for _band in range(3)])
    out = BytesIO()
    picture.save(out, "JPEG", quality=PHOTO_QUALITY)
    return out.getvalue()


def _stored_file(store: NoteStore, note_id: str) -> bytes:
    file_id = re.search(r"\[\[([0-9a-f-]{36})\]\]", strip_html(store.get_note(note_id).content)).group(1)
    return typing.cast(DownloadedFile, file_registry.read_stored_file(file_id)).content_bytes


@pytest.mark.parametrize("compresses_images", [False, True])
def test_a_folder_of_files_images_come_in_compressed_only_when_asked(
    tmp_path: Path, note_store: NoteStore, compresses_images: bool,
) -> None:
    photo = _photo_bytes()
    _write_files(tmp_path, {"photo.jpg": photo, "notes.txt": b"Text"})
    CmdImportFolderOfFiles(
        folder_path=str(tmp_path), selection=_selection([], excluded_files=(), included_files=()), split_mode=SPLIT_NONE,
        content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=ImageChoice(compresses=compresses_images, longest_side_px=2560),
        token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    photo_note = next(note_id for note_id in imported_roots(note_store) if _shown_as(note_store, note_id) == "photo.jpg")
    stored = _stored_file(note_store, photo_note)
    if not compresses_images:
        assert stored == photo
        return
    assert Image.open(BytesIO(stored)).size == (2560, 1920)
    assert len(stored) < len(photo)


def test_a_vaults_linked_image_comes_in_compressed(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {"Trip.md": b"Look:\n\n![[photo.jpg]]\n", "photo.jpg": _photo_bytes()})
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=False, images=ImageChoice(compresses=True, longest_side_px=2560), token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    trip = imported_roots(note_store)[0]
    assert Image.open(BytesIO(_stored_file(note_store, trip))).size == (2560, 1920)


def test_the_image_estimate_counts_the_images_the_import_stores(tmp_path: Path, note_store: NoteStore) -> None:
    photo = _photo_bytes()
    _write_files(tmp_path, {"Trip.md": b"![[shown.jpg]]", "shown.jpg": photo, "unused.jpg": photo, "anim.gif": b"GIF89a"})
    estimate = CmdEstimateImportImages(
        source="obsidian", folder_path=str(tmp_path), selection=_selection([], excluded_files=(), included_files=()),
        split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    assert estimate["imageCount"] == 1
    assert estimate["imageBytes"] == len(photo)
    by_side = typing.cast(dict[str, int], estimate["compressedBytes"])
    assert sorted(by_side) == ["1280", "1920", "2560", "3840"]
    assert 0 < by_side["1280"] < by_side["2560"] < len(photo)
    files_estimate = CmdEstimateImportImages(
        source="files", folder_path=str(tmp_path), selection=_selection([], excluded_files=("unused.jpg",), included_files=()),
        split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN, folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    assert (files_estimate["imageCount"], files_estimate["imageBytes"]) == (1, len(photo))


# The summary says how a folder of files' images come in: each a file in a note of its own,
# shown as its picture (the maintainer, 2026-11-01: inside notes or as files?).
def test_a_folder_of_files_preview_counts_text_files_kept_files_and_images(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {"notes.md": b"# Notes", "a.jpg": b"x", "Sub/b.PNG": b"x", "report.pdf": b"%PDF"})
    preview = CmdPreviewFolderOfFiles(
        folder_path=str(tmp_path), selection=_selection([], excluded_files=(), included_files=()), split_mode=SPLIT_NONE,
        content_format=CONTENT_MARKDOWN, folder_prefix="", imported_at=IMPORTED_AT,
    ).execute()
    assert (preview["textFileCount"], preview["keptFileCount"], preview["keptImageCount"]) == (1, 3, 2)



# Files are shown, not copied (docs/ready-to-build/files-shown-not-copied.md, the maintainer,
# 2026-11-03): no file's text goes into a note under its card; it is kept for search instead.
def test_an_imported_file_is_its_card_alone_with_no_preview_note(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {
        "page.html": b"<html><body><p>Hello <b>page</b></p></body></html>", "tool.py": b"print(1)\n",
        "story.rtf": rb"{\rtf1\ansi Once {\b upon} a time.\par}", "report.pdf": b"%PDF",
    })
    CmdImportFolderOfFiles(
        folder_path=str(tmp_path), selection=_selection([], excluded_files=(), included_files=()), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT, context_tags="",
    ).execute()
    roots = imported_roots(note_store)
    assert len(roots) == 4
    assert all(note_store.get_children(note_id) == [] for note_id in roots)


# Files dropped in a search context (the maintainer, 2026-11-03): "it does not add the tags for
# that search context, so the results don't show up in the search context". Each top note gets
# the context's tags (a comment whole, a tag it has already left out); the notes below inherit them.
def test_a_drop_imports_notes_with_the_search_context_tags(tmp_path: Path, note_store: NoteStore) -> None:
    _write_files(tmp_path, {"plan.md": b"# Plan\n- step one\n- step two", "photo.png": b"\x89PNG fake"})
    CmdImportFolderOfFiles(
        folder_path=str(tmp_path), selection=_selection([], excluded_files=(), included_files=()), split_mode=SPLIT_HEADINGS_AND_LISTS,
        content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN,
        imported_at=IMPORTED_AT, context_tags="work /*two words*/ WORK",
    ).execute()
    roots = imported_roots(note_store)
    assert len(roots) == 2
    for note_id in roots:
        tags = note_store.get_note(note_id).tags
        assert tags.endswith(" work /*two words*/"), tags
    plan = next(note_id for note_id in roots if _shown_as(note_store, note_id) != "photo.png")
    children = note_store.get_children(plan)
    assert children
    assert all("work" not in note_store.get_note(child).tags.split() for child in children)


def test_the_drop_context_gives_the_tags_a_note_made_there_gets() -> None:
    assert drop_context_tags(search="work", folder_filter="", folder_prefix="") == "work"
    assert drop_context_tags(search="", folder_filter="", folder_prefix="") == ""
    # Narrowed to a folder: filed in it, as a new note is, unless it goes into a folder of its own.
    assert drop_context_tags(search="work", folder_filter="Projects/", folder_prefix="").split() == ["Projects/", "work"]
    assert drop_context_tags(search="", folder_filter="Projects/", folder_prefix="") == "Projects/"
    assert drop_context_tags(search="work", folder_filter="Projects/", folder_prefix="Notes") == "work"
