"""Files as the viewer shows them (docs/ready-to-build/files-shown-not-copied.md §4), and their
pill labels. See app/services/file_view.py and docs/ui/references.md.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.services.embedded_references import _format_file_badge
import app.services.file_view as file_view_module
from app.services.code_rendering import is_known_code_language
from app.services.file_view import (
    MAX_VIEW_TEXT_BYTES,
    PREVIEW_DOCUMENT,
    VIEW_PAGE,
    build_file_view,
    view_kind_of,
    plain_text_to_note_html,
    preview_kind_of,
    text_file_badge,
)
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.security.note_html import sanitize_note_html, sanitize_viewed_document_html
from app.security.rendered_html import sanitize_rendered_html

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
    # Every file by its own type (the maintainer, 2026-11-02: TXT for a .css and FILE for an
    # .rtf were "very nonspecific"); its kind only when it has no short extension.
    ("server.log", "text", ".LOG"),
    ("structure.css", "text", ".CSS"),
    ("21083.js", "text", ".JS"),
    ("Harold and Lupus.rtf", "other", ".RTF"),
    ("report.pdf", "pdf", ".PDF"),
    ("archive.zip", "archive", ".ZIP"),
    ("photo.png", "image", ".PNG"),
    ("clip.mp4", "video", ".MP4"),
    ("data.tar.gz", "archive", ".GZ"),
    ("no-extension", "other", "FILE"),
    ("sketch.excalidraw", "excalidraw", "DRAW"),
    ("odd.name with space", "other", "FILE"),
])
def test_the_pill_names_each_file_by_its_extension(filename: str, thumbnail_kind: str, badge: str) -> None:
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
    preview = build_file_view(original_filename=filename, content_bytes=b"a,b\n1,2")
    assert preview.status == "ready"
    assert preview.content_html == "a,b<br>1,2"
    assert preview.render_tag == render_tag


@pytest.mark.parametrize(("filename", "kind"), [
    ("report.pdf", "pdf"), ("Report.PDF", "pdf"), ("notes.txt", "page"), ("readme.md", "page"), ("tool.py", "page"),
    ("data.csv", "page"), ("config.json", "page"), ("plan.docx", "page"), ("story.rtf", "page"), ("page.html", "page"),
    ("archive.zip", ""), ("old.doc", "page"), ("server.log", ""), ("photo.jpg", ""),
])
def test_which_files_the_viewer_shows_and_how(filename: str, kind: str) -> None:
    # A PDF in the browser's own viewer; the rest as note HTML; any other file has Download only.
    assert view_kind_of(filename) == kind


def test_files_the_viewer_doesnt_draw_say_why() -> None:
    assert build_file_view(original_filename="report.pdf", content_bytes=b"%PDF").status == "not_previewable"
    assert build_file_view(original_filename="archive.zip", content_bytes=b"PK").status == "not_previewable"


def test_a_text_file_over_5_mb_shows_its_first_5_mb() -> None:
    at_limit = build_file_view(original_filename="big.txt", content_bytes=b"x" * MAX_VIEW_TEXT_BYTES)
    assert (at_limit.status, at_limit.is_cut) == ("ready", False)
    over = build_file_view(original_filename="big.txt", content_bytes=b"x" * (MAX_VIEW_TEXT_BYTES + 1))
    assert (over.status, over.is_cut, len(over.content_html)) == ("ready", True, MAX_VIEW_TEXT_BYTES)


def test_a_text_file_in_another_encoding_shows_what_can_be_read() -> None:
    latin1 = build_file_view(original_filename="old.csv", content_bytes="café".encode("latin-1"))
    assert (latin1.status, latin1.content_html, latin1.render_tag) == ("ready", "caf\ufffd", "@csv")


def test_the_text_is_kept_line_for_line_and_never_read_as_html() -> None:
    text = "# Title\r\n\r\n  indented & <b>not bold</b>\rlast\n"
    note_html = plain_text_to_note_html(text)
    assert note_html == "# Title<br><br>  indented &amp; &lt;b&gt;not bold&lt;/b&gt;<br>last"
    # The renderers read back exactly the file's text.
    assert extract_plain_text_from_note_html(note_html) == "# Title\n\n  indented & <b>not bold</b>\nlast"


def test_a_utf8_byte_order_mark_is_not_part_of_the_text() -> None:
    preview = build_file_view(original_filename="excel.csv", content_bytes=b"\xef\xbb\xbfa,b")
    assert preview.content_html == "a,b"


# --- Code and HTML previews (docs/ready-to-build/folder-import-and-file-previews.md §5;
# the acceptance checks of 2026-11-01) --------------------------------------------------------


@pytest.mark.parametrize(("filename", "language"), [
    ("script.py", "python"), ("app.JS", "javascript"), ("run.sh", "bash"), ("query.sql", "sql"), ("config.yml", "yaml"),
])
def test_a_code_file_gets_its_code_drawn_in_its_language(filename: str, language: str) -> None:
    preview = build_file_view(original_filename=filename, content_bytes=b"x = 1\nprint(x)\n")
    assert (preview.status, preview.render_tag) == ("ready", f"@code={language}")
    assert extract_plain_text_from_note_html(preview.content_html) == "x = 1\nprint(x)"
    assert preview_kind_of(filename) == "code"


def test_every_code_language_is_one_code_drawing_knows() -> None:
    for language in file_view_module._CODE_LANGUAGES_BY_EXTENSION.values():
        assert is_known_code_language(language), language


def test_a_web_page_shows_its_body_sanitized_without_scripts_styles_or_head() -> None:
    page = (
        b"<html><head><title>Tab title</title><style>p{color:red}</style><script>alert(1)</script></head>"
        b"<body onload='x()'><h1>Trip</h1><p>Day <b>one</b></p><script>steal()</script></body></html>"
    )
    preview = build_file_view(original_filename="page.html", content_bytes=page)
    assert (preview.status, preview.render_tag) == ("ready", "")
    assert "<b>one</b>" in preview.content_html and "<h1>Trip</h1>" in preview.content_html
    for gone in ("Tab title", "color:red", "alert", "steal", "onload", "<script"):
        assert gone not in preview.content_html
    empty = build_file_view(original_filename="blank.htm", content_bytes=b"<html><body><script>x</script></body></html>")
    assert empty.status == "no_text"


# --- Word documents and RTFs (the maintainer, 2026-11-02) ----------------------------------


def _word_document(body: str) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f"{body}</w:body></w:document>"))
    return out.getvalue()


_W = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)
_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# A 1x1 PNG.
_PICTURE = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63fccf0c040f00048501809a98c8210000000049454e44ae426082"
)


def _full_word_document(body: str, *, picture: bytes, styles: str) -> bytes:
    """A .docx as Word writes one: styles, a bullet list's numbering, a link and a picture."""
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", (
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="png" ContentType="image/png"/><Default Extension="xml" ContentType="application/xml"/></Types>'))
        archive.writestr("_rels/.rels", (
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_RELATIONSHIPS}/officeDocument" Target="word/document.xml"/></Relationships>'))
        archive.writestr("word/_rels/document.xml.rels", (
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rLink" Type="{_RELATIONSHIPS}/hyperlink" Target="https://example.org/harbor" TargetMode="External"/>'
            f'<Relationship Id="rPic" Type="{_RELATIONSHIPS}/image" Target="media/image1.png"/>'
            f'<Relationship Id="rStyles" Type="{_RELATIONSHIPS}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rNum" Type="{_RELATIONSHIPS}/numbering" Target="numbering.xml"/></Relationships>'))
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/numbering.xml", (
            f'<?xml version="1.0"?><w:numbering {_W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/>'
            '</w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'))
        archive.writestr("word/media/image1.png", picture)
        archive.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {_W}><w:body>{body}</w:body></w:document>')
    return out.getvalue()


_STYLES = f'<?xml version="1.0"?><w:styles {_W}><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>'
_PLAN = (
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Harbor plan</w:t></w:r></w:p>'
    '<w:p><w:r><w:t xml:space="preserve">A </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>'
    '<w:r><w:t xml:space="preserve"> and </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r>'
    '<w:r><w:t xml:space="preserve"> line, </w:t></w:r><w:hyperlink r:id="rLink"><w:r><w:t>a link</w:t></w:r></w:hyperlink></w:p>'
    '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>First point</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Second point</w:t></w:r></w:p>'
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Day</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>City</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    '<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture 1" descr="A harbor"/><a:graphic>'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:blipFill><a:blip r:embed="rPic"/>'
    '</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
)


# Word previews come through mammoth (the maintainer, 2026-11-03), from the document's structure.
def test_a_word_document_keeps_headings_bold_italics_links_lists_tables_and_pictures() -> None:
    content = _full_word_document(_PLAN, picture=_PICTURE, styles=_STYLES)
    preview = build_file_view(original_filename="plan.docx", content_bytes=content)
    assert (preview.status, preview.render_tag) == ("ready", "")
    picture = base64.b64encode(_PICTURE).decode()
    assert preview.content_html == (
        '<h1>Harbor plan</h1><p>A <strong>bold</strong> and <em>italic</em> line, <a href="https://example.org/harbor">a link</a></p>'
        "<ul><li>First point</li><li>Second point</li></ul>"
        "<table><tbody><tr><td><p>Day</p></td><td><p>City</p></td></tr></tbody></table>"
        f'<p><img alt="A harbor" src="data:image/png;base64,{picture}"></p>'
    )
    assert preview_kind_of("plan.docx") == PREVIEW_DOCUMENT


def test_a_word_document_shows_without_pictures_that_would_make_it_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    viewer_limit = 4096
    monkeypatch.setattr(file_view_module, "MAX_VIEW_HTML_BYTES", viewer_limit)
    content = _full_word_document(_PLAN, picture=bytes(viewer_limit), styles=_STYLES)
    preview = build_file_view(original_filename="plan.docx", content_bytes=content)
    assert preview.status == "ready"
    assert "<img" not in preview.content_html
    assert preview.content_html.startswith("<h1>Harbor plan</h1>")


@pytest.mark.parametrize("content", [
    # A DTD in any part: Word writes none, so one could only expand entities without end.
    _full_word_document(_PLAN, picture=_PICTURE, styles='<!DOCTYPE x [<!ENTITY a "aaaa">]>' + _STYLES),
    _full_word_document("<w:p><w:r><w:t>broken", picture=_PICTURE, styles=_STYLES),
    b"not a zip",
])
def test_a_word_document_that_cant_be_read_safely_has_no_preview(content: bytes) -> None:
    assert build_file_view(original_filename="plan.docx", content_bytes=content).status == "not_readable"


def test_an_rtf_gets_a_preview_of_its_paragraphs() -> None:
    preview = build_file_view(original_filename="Harold and Lupus.rtf", content_bytes=rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}\f0 Once {\i upon} a time.\par The end.\par}")
    assert (preview.status, preview.content_html) == ("ready", "<p>Once <i>upon</i> a time.</p><p>The end.</p>")


def test_a_document_that_cant_be_read_says_so() -> None:
    assert build_file_view(original_filename="broken.docx", content_bytes=b"not a zip").status == "not_readable"
    # Word 97-2003's .doc shows its text since 2026-11-03: a damaged one says it can't be read.
    assert build_file_view(original_filename="old.doc", content_bytes=b"\xd0\xcf").status == "not_readable"


def test_a_word_97_document_opens_as_its_paragraphs() -> None:
    content = (Path(__file__).resolve().parents[1] / "fixtures" / "word97" / "plan.doc").read_bytes()
    assert view_kind_of("Harbor plan.doc") == VIEW_PAGE
    view = build_file_view(original_filename="Harbor plan.doc", content_bytes=content)
    assert view.status == "ready"
    assert view.content_html.startswith("<p>Harbor plan</p><p>The café opens at nine \u2014 bring the ledger\u2019s copy.</p>")


# --- The viewer's route (files-shown-not-copied.md §4, acceptance checks 16 and 20) -----------


def test_the_view_route_draws_a_file_as_its_note_would_and_names_a_pdfs_viewer(tmp_path: Path) -> None:
    script = '''
from fastapi.testclient import TestClient
from app.main import app
from app.config import API_PREFIX
from app.services.tokens import token_service

token = token_service.create_token(client_info="fixture", owner_tab_id="tab", dek=None)
headers = {"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}

def upload(client, name, content):
    return client.post(API_PREFIX + "/files/upload", headers=headers, files={"file": (name, content, "application/octet-stream")}).json()["file_id"]

with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    ids = {name: upload(client, name, content) for name, content in (
        ("readme.md", b"# Harbor\\n\\nA **bold** plan."), ("tool.py", b"print('harbor')\\n"), ("lease.pdf", b"%PDF lease"),
        ("broken.docx", b"not a zip"), ("archive.zip", b"PK"),
    )}
    view = lambda name: client.get(API_PREFIX + "/files/" + ids[name] + "/view", headers=headers)
    markdown = view("readme.md").json()
    assert (markdown["kind"], markdown["status"], markdown["isCut"]) == ("page", "ready", False), markdown
    assert "<h1" in markdown["html"] and "<strong>bold</strong>" in markdown["html"], markdown["html"]
    code = view("tool.py").json()
    assert "highlight" in code["html"] or "code" in code["html"], code["html"]
    assert view("lease.pdf").json() == {"name": "lease.pdf", "kind": "pdf", "status": "ready", "html": "", "isCut": False}
    assert view("broken.docx").json()["status"] == "not_readable"
    assert view("archive.zip").status_code == 404
    assert client.get(API_PREFIX + "/files/" + ids["readme.md"] + "/view", headers={"Origin": "http://localhost"}).status_code == 401
print("VIEW OK")
'''
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-3000:])
    assert "VIEW OK" in result.stdout


# The viewer shows a document's bold, italics, underline, strikethrough and highlights (the
# maintainer, 2026-11-03: a .doc highlighted in colours showed plain). A highlight is a
# <mark class="file-highlight-NAME">, NAME one of Word's 16, and nothing else of a file's style.
def test_a_word_97_documents_look_shows_in_the_viewer() -> None:
    content = (Path(__file__).resolve().parents[1] / "fixtures" / "word97" / "styled.doc").read_bytes()
    view = build_file_view(original_filename="styled.doc", content_bytes=content)
    assert view.content_html == (
        "<p>Plain <b>bold</b> <i>italic</i> <u>under</u> <s>struck</s> "
        '<mark class="file-highlight-yellow">yellow mark</mark> <mark class="file-highlight-green">green mark</mark> end.</p>'
    )


# Word writes an RTF's highlight as \highlightN, TextEdit as a background colour \cbN (white
# its end): both a colour of the table, shown as the nearest of Word's highlights.
WORD_HIGHLIGHT_RTF = (
    rb"{\rtf1\ansi{\fonttbl\f0 Times;}{\colortbl;\red0\green0\blue0;\red255\green255\blue0;\red0\green255\blue255;}"
    rb"\f0 A {\highlight2 yellow} and \highlight3 cyan\highlight0  word, \ul under\ulnone  and \strike struck\strike0 .\par}"
)
TEXTEDIT_HIGHLIGHT_RTF = (
    rb"{\rtf1\ansi\cocoartf2761{\fonttbl\f0 Times-Roman;}{\colortbl;\red255\green255\blue255;\red0\green0\blue0;"
    rb"\red255\green255\blue11;\red34\green255\blue6;}\f0 Plain \cb3 yellow mark\cb1  \cb4 green mark\cb1  end.\par}"
)


def test_an_rtfs_highlights_underline_and_strikethrough_show_in_the_viewer() -> None:
    assert build_file_view(original_filename="word.rtf", content_bytes=WORD_HIGHLIGHT_RTF).content_html == (
        '<p>A <mark class="file-highlight-yellow">yellow</mark> and <mark class="file-highlight-cyan">cyan</mark> word, '
        "<u>under</u> and <s>struck</s>.</p>"
    )
    assert build_file_view(original_filename="textedit.rtf", content_bytes=TEXTEDIT_HIGHLIGHT_RTF).content_html == (
        '<p>Plain <mark class="file-highlight-yellow">yellow mark</mark> <mark class="file-highlight-green">green mark</mark> end.</p>'
    )


def test_a_word_documents_highlights_underline_and_strikethrough_show_in_the_viewer() -> None:
    body = (
        '<w:p><w:r><w:t xml:space="preserve">A </w:t></w:r><w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>yellow</w:t></w:r>'
        '<w:r><w:t xml:space="preserve"> and </w:t></w:r><w:r><w:rPr><w:highlight w:val="darkCyan"/></w:rPr><w:t>teal</w:t></w:r>'
        '<w:r><w:t xml:space="preserve">, </w:t></w:r><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>under</w:t></w:r>'
        '<w:r><w:t xml:space="preserve"> and </w:t></w:r><w:r><w:rPr><w:strike/></w:rPr><w:t>struck</w:t></w:r></w:p>'
    )
    view = build_file_view(original_filename="marked.docx", content_bytes=_full_word_document(body, picture=_PICTURE, styles=_STYLES))
    assert view.content_html == (
        '<p>A <mark class="file-highlight-yellow">yellow</mark> and <mark class="file-highlight-dark-cyan">teal</mark>, '
        "<u>under</u> and <s>struck</s></p>"
    )


def test_a_highlight_shows_in_the_viewer_only_and_carries_nothing_else() -> None:
    from_file = '<p><mark class="file-highlight-yellow evil" style="color:red">a</mark><mark class="other">b</mark></p>'
    assert sanitize_viewed_document_html(from_file) == '<p><mark class="file-highlight-yellow">a</mark><mark>b</mark></p>'
    # A stored note keeps no highlight colour: its mark is a plain one.
    assert sanitize_note_html(from_file) == "<p><mark>a</mark><mark>b</mark></p>"
    # The rendered view lets the colour through.
    assert 'class="file-highlight-yellow"' in sanitize_rendered_html('<mark class="file-highlight-yellow">a</mark>')
