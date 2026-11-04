"""How the reading worker reads a PDF's words (file_text_worker.py; the maintainer, 2026-11-03).

pypdf read some PDFs without the spaces between words ("Adolescentdrivershavethehighestrate"),
so neither search nor find saw their phrases. PDFium (pypdfium2) puts most of them back from
where the words sit; on some lines it doesn't, and there the gaps between the letters' boxes
say where the spaces are. Which of the two readings a page keeps is decided by how much of it
reads as words run together or letters standing apart.
"""

from __future__ import annotations

from app.services.file_text_search import TEXT_READER_VERSIONS
from app.services.file_text_worker import Glyph, line_with_gap_spaces, reading_trouble

SIZE = 10.0
LETTER = 5.0
# A word space with no space character drawn: 0.4 of the font size.
WORD_GAP = 4.0


def _line(words: list[str], *, letter_gap: float, word_gap: float) -> list[Glyph]:
    """The glyphs of words set on one line, each letter LETTER wide."""
    glyphs = []
    x = 0.0
    for word_index, word in enumerate(words):
        if word_index > 0:
            x += word_gap - letter_gap
        for letter_index, letter in enumerate(word):
            if letter_index > 0:
                x += letter_gap
            glyphs.append(Glyph(char=letter, left=x, right=x + LETTER, bottom=0.0, top=SIZE, size=SIZE))
            x += LETTER
    return glyphs


def test_words_set_apart_without_spaces_get_them_back() -> None:
    glyphs = _line(["Adolescent", "drivers", "have", "the", "highest"], letter_gap=0.0, word_gap=WORD_GAP)
    assert line_with_gap_spaces(glyphs) == "Adolescent drivers have the highest"


def test_a_space_already_there_is_not_doubled() -> None:
    glyphs = _line(["one", "two"], letter_gap=0.0, word_gap=0.0)
    glyphs.insert(3, Glyph(char=" ", left=LETTER * 3, right=LETTER * 3, bottom=0.0, top=SIZE, size=SIZE))
    assert line_with_gap_spaces(glyphs) == "one two"


def test_a_letter_spaced_line_stays_whole() -> None:
    # A heading set with wide tracking: every gap is the same, none is a word's.
    glyphs = _line(["antimicrobial"], letter_gap=WORD_GAP, word_gap=WORD_GAP)
    assert line_with_gap_spaces(glyphs) == "antimicrobial"


def test_a_line_whose_letters_dont_touch_gets_no_spaces_from_gaps() -> None:
    # Boxes narrower than the letters (some data sheets): the gaps tell nothing.
    glyphs = _line(["for", "any", "such"], letter_gap=SIZE * 0.3, word_gap=SIZE * 0.9)
    assert line_with_gap_spaces(glyphs) == "foranysuch"


def test_letters_on_different_lines_are_never_joined_by_a_space() -> None:
    first = _line(["end"], letter_gap=0.0, word_gap=0.0)
    second = [glyph._replace(bottom=-SIZE * 2, top=-SIZE, left=glyph.left + SIZE * 9, right=glyph.right + SIZE * 9) for glyph in _line(["next"], letter_gap=0.0, word_gap=0.0)]
    assert line_with_gap_spaces(first + second) == "endnext"


def test_the_reading_with_fewer_words_run_together_or_letters_apart_is_the_better() -> None:
    run_together = "Adolescentdrivershavethehighestrateofmotorvehiclecrashes"
    spaced = "Adolescent drivers have the highest rate of motor vehicle crashes"
    letters_apart = "a n t i m i c r o b i a l"
    assert reading_trouble(spaced) < reading_trouble(run_together)
    assert reading_trouble("antimicrobial") < reading_trouble(letters_apart)
    # A short word is no stray letter.
    assert reading_trouble("a cat is on the mat") == 0


def test_every_pdf_is_read_again_by_the_new_reader() -> None:
    # 1 was pypdf's: every PDF read before is read again, by itself, in the background.
    assert TEXT_READER_VERSIONS[".pdf"] == 2
