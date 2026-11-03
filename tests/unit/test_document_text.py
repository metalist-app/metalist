"""Word (.docx) and RTF documents read with Python alone (the maintainer, 2026-11-02: MetaList's
own reader, no new dependency): as note HTML for a preview note, and as text for search."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

import app.services.document_text as document_text_module
from app.services.document_text import UnreadableDocument, document_html, document_text

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(body: str) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return out.getvalue()


NO_STYLE = ""


def _paragraph(text: str, *, style: str, listed: bool) -> str:
    properties = ""
    if style or listed:
        properties = "<w:pPr>"
        if style:
            properties += f'<w:pStyle w:val="{style}"/>'
        if listed:
            properties += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        properties += "</w:pPr>"
    return f"<w:p>{properties}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


LETTER = _docx(
    _paragraph("Harold and Lupus", style="Heading1", listed=False)
    + "<w:p><w:r><w:t xml:space=\"preserve\">A </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"
      "<w:r><w:t xml:space=\"preserve\"> and </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r><w:r><w:t> line &amp; more.</w:t></w:r></w:p>"
    + _paragraph("First point", style=NO_STYLE, listed=True) + _paragraph("Second point", style=NO_STYLE, listed=True)
    + "<w:tbl><w:tr><w:tc>" + _paragraph("Day", style=NO_STYLE, listed=False) + "</w:tc><w:tc>" + _paragraph("City", style=NO_STYLE, listed=False) + "</w:tc></w:tr>"
      "<w:tr><w:tc>" + _paragraph("1", style=NO_STYLE, listed=False) + "</w:tc><w:tc>" + _paragraph("Lisbon", style=NO_STYLE, listed=False) + "</w:tc></w:tr></w:tbl>"
)


def test_a_word_document_keeps_its_headings_bold_italics_lists_and_tables() -> None:
    assert document_html("letter.docx", LETTER) == (
        "<h1>Harold and Lupus</h1>"
        "<p>A <b>bold</b> and <i>italic</i> line &amp; more.</p>"
        "<ul><li>First point</li><li>Second point</li></ul>"
        "<table><tr><td>Day</td><td>City</td></tr><tr><td>1</td><td>Lisbon</td></tr></table>"
    )


def test_a_word_documents_text_reads_paragraph_after_paragraph() -> None:
    assert document_text("letter.docx", LETTER) == (
        "Harold and Lupus\nA bold and italic line & more.\nFirst point\nSecond point\nDay\tCity\n1\tLisbon"
    )


RTF = (
    rb"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Helvetica;}}{\colortbl;\red0\green0\blue0;}"
    rb"{\*\generator Writer;}{\info{\title Secret title}}"
    rb"\f0\fs24 Harold and Lupus\par "
    rb"A {\b bold} and {\i italic} word, caf\'e9 and " + b"\\" + rb"u8364? euro.\par "
    rb"Tab\tab here\line next line\par}"
)


def test_an_rtf_keeps_its_paragraphs_bold_and_italics_and_drops_its_tables_of_fonts() -> None:
    assert document_html("letter.rtf", RTF) == (
        "<p>Harold and Lupus</p>"
        "<p>A <b>bold</b> and <i>italic</i> word, café and € euro.</p>"
        "<p>Tab\there<br>next line</p>"
    )
    assert document_text("letter.rtf", RTF) == "Harold and Lupus\nA bold and italic word, café and € euro.\nTab\there\nnext line"


@pytest.mark.parametrize(("name", "content"), [
    ("broken.docx", b"not a zip"),
    ("empty.docx", _docx("").replace(b"word/document.xml", b"word/other.xml!!")),
    ("doctype.docx", b""),
    ("broken.rtf", b"plain text, no rtf"),
])
def test_a_document_that_cant_be_read_says_so(name: str, content: bytes) -> None:
    if name == "doctype.docx":
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document/>')
        content = out.getvalue()
    with pytest.raises(UnreadableDocument):
        document_html(name, content)


# TextEdit ends each line with a backslash and a newline, which RTF reads as \par: an article's
# title, byline and paragraphs ran together ("ProblemStuart Bradford NYT Aug 18 2009After a",
# the maintainer, 2026-11-03).
TEXTEDIT_RTF = (
    b"{\\rtf1\\ansi\\ansicpg1252\\cocoartf2639\n"
    b"{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n"
    b"{\\colortbl;\\red255\\green255\\blue255;}\n"
    b"\\pard\\tx560\\pardirnatural\\partightenfactor0\n"
    b"\n"
    b"\\f0\\b\\fs24 \\cf0 Weight Lifting May Help\\\n"
    b"\\b0 Stuart Bradford NYT Aug 18 2009\\\n"
    b"\\\n"
    b"After a woman has surgery.\\\r\n"
    b"Last line.}"
)


def test_textedits_line_ends_are_paragraphs() -> None:
    assert document_text("article.rtf", TEXTEDIT_RTF) == (
        "Weight Lifting May Help\nStuart Bradford NYT Aug 18 2009\nAfter a woman has surgery.\nLast line."
    )
    assert document_html("article.rtf", TEXTEDIT_RTF) == (
        "<p><b>Weight Lifting May Help</b></p><p>Stuart Bradford NYT Aug 18 2009</p>"
        "<p>After a woman has surgery.</p><p>Last line.</p>"
    )


# RTF names some characters with control words (\emdash, \rquote...): skipped, they joined the
# words around them ("450,000 babiesthat's", page ranges "521534"; the maintainer's RTFs,
# 2026-11-03, against macOS textutil).
NAMED_CHARACTERS_RTF = (
    b"{\\rtf1\\ansi\\ansicpg1252\n"
    b"{\\fonttbl\\f0\\fswiss Helvetica;}\n"
    b"\\f0 450,000 babies\\emdash that\\rquote s 1 of 9, pages 521\\endash 534.\\par\n"
    b"\\ldblquote Quoted\\rdblquote  and \\lquote single\\rquote .\\par\n"
    b"\\bullet  item\\tab one\\emspace two\\enspace three\\qmspace four\\par\n"
    b"A\\page B\\par}"
)


def test_rtfs_named_characters_are_their_characters() -> None:
    assert document_text("named.rtf", NAMED_CHARACTERS_RTF) == (
        "450,000 babies—that’s 1 of 9, pages 521–534.\n"
        "“Quoted” and ‘single’.\n"
        "• item\tone two three four\n"
        "A\nB"
    )


# Word 97-2003 documents (.doc), read with olefile and Word's own table of text pieces (the
# maintainer, 2026-11-03: 113 in the vault, neither searchable nor shown). The fixtures were
# written by macOS textutil from this text.
WORD97 = Path(__file__).resolve().parents[1] / "fixtures" / "word97"


def test_a_word_97_documents_paragraphs_are_its_text() -> None:
    content = (WORD97 / "plan.doc").read_bytes()
    assert document_text("plan.doc", content) == (
        "Harbor plan\n"
        "The café opens at nine \u2014 bring the ledger\u2019s copy.\n"
        "Second paragraph, with \u201cquotes\u201d and 450,000 visitors."
    )
    assert document_html("plan.doc", content).startswith("<p>Harbor plan</p><p>The café opens")


def test_a_word_97_documents_link_shows_its_words_and_its_table_its_cells() -> None:
    content = (WORD97 / "table.doc").read_bytes()
    assert document_text("table.doc", content) == (
        "Before the table, see the plan.\nDay\nCity\n1\nLisbon\nAfter the table."
    )


@pytest.mark.parametrize("content", [b"not a document", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600])
def test_a_doc_that_cant_be_read_says_so(content: bytes) -> None:
    with pytest.raises(UnreadableDocument):
        document_text("broken.doc", content)


def test_a_word_97_character_past_the_basic_range_reads_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    # A character past U+FFFF is two UTF-16 units in a .doc: each keeps its own file position
    # (so its look), and the two read as one character again.
    text = "A \ud83c\udf0a wave\r"
    monkeypatch.setattr(document_text_module, "_doc_text", lambda content: (text, [document_text_module._PLAIN] * len(text)))
    assert [run.text for block in document_text_module._doc_blocks(b"") for run in block.runs] == ["A \U0001f30a wave"]
