"""Dropped .txt, .md, .csv and .json files: their pill label and their preview child note.

See app/services/file_text_preview.py and docs/ui/references.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.usecases.create_file_preview_child as preview_child_module
from app.services.embedded_references import _format_file_badge
import app.services.file_text_preview as file_text_preview_module
from app.services.code_rendering import is_known_code_language
from app.services.file_text_preview import (
    MAX_PREVIEW_BYTES,
    build_file_text_preview,
    plain_text_to_note_html,
    preview_kind_of,
    text_file_badge,
)
from app.services.note_store import NoteRecord
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.usecases.create_file_preview_child import CmdCreateFilePreviewChild

FILE_ID = "9ec1c81f-2d96-46f1-a455-e3e77798ae1f"


@pytest.mark.parametrize(("filename", "thumbnail_kind", "badge"), [
    ("notes.txt", "text", ".TXT"),
    ("readme.md", "text", ".MD"),
    ("README.MD", "text", ".MD"),
    ("guide.markdown", "text", ".MD"),
    ("data.csv", "text", ".CSV"),
    ("config.json", "other", ".JSON"),
    # Browsers may send no text MIME type for Markdown: the extension still names it.
    ("readme.md", "other", ".MD"),
    ("server.log", "text", "TXT"),
    ("report.pdf", "pdf", "PDF"),
    ("archive.zip", "archive", "ZIP"),
    ("photo.png", "image", "IMG"),
    ("no-extension", "other", "FILE"),
])
def test_the_pill_names_text_files_by_extension(filename: str, thumbnail_kind: str, badge: str) -> None:
    assert _format_file_badge(thumbnail_kind=thumbnail_kind, original_filename=filename) == badge


def test_only_txt_md_csv_and_json_have_a_text_badge() -> None:
    assert text_file_badge("a.txt") == ".TXT"
    assert text_file_badge("a.md") == ".MD"
    assert text_file_badge("a.csv") == ".CSV"
    assert text_file_badge("a.log") == ""
    assert text_file_badge("a.json") == ".JSON"
    assert text_file_badge("a.yaml") == ""
    assert text_file_badge("md") == ""


@pytest.mark.parametrize(("filename", "render_tag"), [
    ("notes.txt", ""),
    ("readme.md", "@markdown"),
    ("guide.markdown", "@markdown"),
    ("data.csv", "@csv"),
    ("config.json", "@json"),
])
def test_a_previewable_file_gets_its_text_and_render_tag(filename: str, render_tag: str) -> None:
    preview = build_file_text_preview(original_filename=filename, content_bytes=b"a,b\n1,2")
    assert preview.status == "ready"
    assert preview.content_html == "a,b<br>1,2"
    assert preview.render_tag == render_tag


def test_files_without_a_preview_say_why() -> None:
    # A PDF gets no preview note: its text is to be searchable with the file instead.
    assert build_file_text_preview(original_filename="report.pdf", content_bytes=b"%PDF").status == "not_previewable"
    assert build_file_text_preview(original_filename="server.log", content_bytes=b"x").status == "not_previewable"
    assert build_file_text_preview(original_filename="archive.zip", content_bytes=b"PK").status == "not_previewable"
    too_large = build_file_text_preview(original_filename="big.txt", content_bytes=b"x" * (MAX_PREVIEW_BYTES + 1))
    assert (too_large.status, too_large.content_html, too_large.render_tag) == ("too_large", "", "")
    at_limit = build_file_text_preview(original_filename="big.txt", content_bytes=b"x" * MAX_PREVIEW_BYTES)
    assert at_limit.status == "ready"
    latin1 = build_file_text_preview(original_filename="old.csv", content_bytes="café".encode("latin-1"))
    assert (latin1.status, latin1.content_html, latin1.render_tag) == ("not_text", "", "")


def test_the_text_is_kept_line_for_line_and_never_read_as_html() -> None:
    text = "# Title\r\n\r\n  indented & <b>not bold</b>\rlast\n"
    note_html = plain_text_to_note_html(text)
    assert note_html == "# Title<br><br>  indented &amp; &lt;b&gt;not bold&lt;/b&gt;<br>last"
    # The renderers read back exactly the file's text.
    assert extract_plain_text_from_note_html(note_html) == "# Title\n\n  indented & <b>not bold</b>\nlast"


def test_a_utf8_byte_order_mark_is_not_part_of_the_text() -> None:
    preview = build_file_text_preview(original_filename="excel.csv", content_bytes=b"\xef\xbb\xbfa,b")
    assert preview.content_html == "a,b"


def _record(note_id: str, content: str) -> NoteRecord:
    return NoteRecord(
        id=note_id, parent_id=None, prev_id=None, next_id=None, is_collapsed=False, content=content,
        tags="", proposed_tags="", tag_terms=frozenset(), non_meta_tag_terms=frozenset(),
        proposed_tag_terms=frozenset(), proposed_non_meta_tag_terms=frozenset(),
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


class _FakeStore:
    def __init__(self, parent: NoteRecord, children: list[str]) -> None:
        self._parent = parent
        self._children = children

    def get(self, note_id: str) -> NoteRecord:
        assert note_id == self._parent.id
        return self._parent

    def children(self, parent_id: str) -> list[str]:
        assert parent_id == self._parent.id
        return list(self._children)


def _run(monkeypatch: pytest.MonkeyPatch, *, filename: str, content_bytes: bytes, parent_content: str,
         children: list[str], initial_tags: str) -> tuple[dict[str, str], list[dict[str, object]]]:
    monkeypatch.setattr(preview_child_module, "store", _FakeStore(_record("parent", parent_content), children))
    monkeypatch.setattr(preview_child_module, "download_file", lambda file_id, token: SimpleNamespace(
        record=SimpleNamespace(original_filename=filename), content_bytes=content_bytes))
    monkeypatch.setattr(preview_child_module, "compute_initial_tags_for_new_note",
                        lambda parent_id, search_query: initial_tags)
    inserted: list[dict[str, object]] = []

    def _insert(note_id, parent_id, prev_id, next_id, token, *, content, tags, proposed_tags):
        inserted.append({"parent_id": parent_id, "prev_id": prev_id, "next_id": next_id, "content": content,
                         "tags": tags, "proposed_tags": proposed_tags})

    monkeypatch.setattr(preview_child_module, "apply_insert_note", _insert)
    monkeypatch.setattr(preview_child_module, "build_created_note_undo_record", lambda note_id: note_id)
    monkeypatch.setattr(preview_child_module, "record_create", lambda client_id, undo_context, record, viewport: None)
    result = CmdCreateFilePreviewChild(
        parent_note_id="parent", file_id=FILE_ID, search_query=None, token="token", client_id="client",
        undo_context="tab:1|search:|epoch:0", viewport={},
    ).execute()
    return result, inserted


def test_the_preview_is_the_last_child_of_the_note_holding_the_pill(monkeypatch: pytest.MonkeyPatch) -> None:
    result, inserted = _run(monkeypatch, filename="readme.md", content_bytes=b"# Hi\n- one",
                            parent_content=f"![[{FILE_ID}]]", children=["first", "second"], initial_tags="")
    assert result["status"] == "created"
    assert inserted == [{"parent_id": "parent", "prev_id": "second", "next_id": None,
                         "content": "# Hi<br>- one", "tags": "@markdown", "proposed_tags": ""}]


def test_a_note_without_children_gets_its_first_child(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, inserted = _run(monkeypatch, filename="data.csv", content_bytes=b"a,b",
                             parent_content=f"<div>![[{FILE_ID}]]</div>", children=[], initial_tags="")
    assert (inserted[0]["prev_id"], inserted[0]["next_id"], inserted[0]["tags"]) == (None, None, "@csv")


def test_the_preview_keeps_the_search_tags_a_new_child_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, inserted = _run(monkeypatch, filename="data.csv", content_bytes=b"a,b",
                             parent_content=f"![[{FILE_ID}]]", children=[], initial_tags="project")
    assert inserted[0]["tags"] == "project @csv"
    _result, inserted = _run(monkeypatch, filename="notes.txt", content_bytes=b"a",
                             parent_content=f"![[{FILE_ID}]]", children=[], initial_tags="project")
    assert inserted[0]["tags"] == "project"


def test_a_file_without_a_preview_creates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    result, inserted = _run(monkeypatch, filename="big.txt", content_bytes=b"x" * (MAX_PREVIEW_BYTES + 1),
                            parent_content=f"![[{FILE_ID}]]", children=[], initial_tags="")
    assert (result, inserted) == ({"status": "too_large"}, [])
    result, inserted = _run(monkeypatch, filename="archive.zip", content_bytes=b"PK",
                            parent_content=f"![[{FILE_ID}]]", children=[], initial_tags="")
    assert (result, inserted) == ({"status": "not_previewable"}, [])
    result, inserted = _run(monkeypatch, filename="report.pdf", content_bytes=b"%PDF",
                            parent_content=f"![[{FILE_ID}]]", children=[], initial_tags="")
    assert (result, inserted) == ({"status": "not_previewable"}, [])


def test_the_note_must_hold_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        _run(monkeypatch, filename="readme.md", content_bytes=b"# Hi", parent_content="no pill here",
             children=[], initial_tags="")



# --- Code and HTML previews (docs/ready-to-build/folder-import-and-file-previews.md §5;
# the acceptance checks of 2026-11-01) --------------------------------------------------------


@pytest.mark.parametrize(("filename", "language"), [
    ("script.py", "python"), ("app.JS", "javascript"), ("run.sh", "bash"), ("query.sql", "sql"), ("config.yml", "yaml"),
])
def test_a_code_file_gets_its_code_drawn_in_its_language(filename: str, language: str) -> None:
    preview = build_file_text_preview(original_filename=filename, content_bytes=b"x = 1\nprint(x)\n")
    assert (preview.status, preview.render_tag) == ("ready", f"@code={language}")
    assert extract_plain_text_from_note_html(preview.content_html) == "x = 1\nprint(x)"
    assert preview_kind_of(filename) == "code"


def test_every_code_language_is_one_code_drawing_knows() -> None:
    for language in file_text_preview_module._CODE_LANGUAGES_BY_EXTENSION.values():
        assert is_known_code_language(language), language


def test_a_web_page_shows_its_body_sanitized_without_scripts_styles_or_head() -> None:
    page = (
        b"<html><head><title>Tab title</title><style>p{color:red}</style><script>alert(1)</script></head>"
        b"<body onload='x()'><h1>Trip</h1><p>Day <b>one</b></p><script>steal()</script></body></html>"
    )
    preview = build_file_text_preview(original_filename="page.html", content_bytes=page)
    assert (preview.status, preview.render_tag) == ("ready", "")
    assert "<b>one</b>" in preview.content_html and "<h1>Trip</h1>" in preview.content_html
    for gone in ("Tab title", "color:red", "alert", "steal", "onload", "<script"):
        assert gone not in preview.content_html
    empty = build_file_text_preview(original_filename="blank.htm", content_bytes=b"<html><body><script>x</script></body></html>")
    assert empty.status == "no_text"
