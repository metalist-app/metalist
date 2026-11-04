import pytest

from app.services.credential_display import CredentialDisplay
from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import format_note_content_for_view
from app.services.latex_rendering import render_latex_math_to_html
from app.services.latex_rendering import render_latex_to_html


def test_render_latex_to_html_without_delimiters_uses_block_math() -> None:
    rendered = render_latex_to_html(r"\frac{1}{2}")
    assert rendered.has_error is False
    assert rendered.error_message == ""
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">' in rendered.html
    assert "<mfrac>" in rendered.html


def test_render_latex_to_html_with_inline_and_display_segments() -> None:
    rendered = render_latex_to_html("before $x^2$ middle $$y^2$$ after")
    assert rendered.has_error is False
    assert "before " in rendered.html
    assert " middle " in rendered.html
    assert " after" in rendered.html
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">' in rendered.html
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">' in rendered.html


def test_render_latex_to_html_invalid_input_returns_error_markup() -> None:
    rendered = render_latex_to_html(r"\begin{matrix}1&2")
    assert rendered.has_error is True
    assert rendered.error_message == ""
    assert "Invalid LaTeX" in rendered.html
    assert r"\begin{matrix}1&amp;2" in rendered.html


def test_markup_typed_in_formula_text_shows_as_text_in_the_note() -> None:
    shown = format_note_content_for_view(
        content_html="<div>$$\\text{&lt;b&gt;x&lt;/b&gt;}$$</div>",
        tags="@markdown",
        credentials=CredentialDisplay.DOTS,
    )
    assert "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>" in shown
    assert "<b>" not in shown


# Every construct whose argument latex2mathml copies into the MathML as it is.
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\text{<b>x</b>}", "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>"),
        (r"\textrm{<b>x</b>}", "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>"),
        (r"\textbf{<b>x</b>}", '<mtext mathvariant="bold">&lt;b&gt;x&lt;/b&gt;</mtext>'),
        (r"\textit{<b>x</b>}", '<mtext mathvariant="italic">&lt;b&gt;x&lt;/b&gt;</mtext>'),
        (r"\mbox{<b>x</b>}", "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>"),
        (r"\hbox{<b>x</b>}", "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>"),
        (r"\fbox{<b>x</b>}", "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>"),
        (r"\verb|<b>|", '<mtext mathvariant="monospace">&lt;b&gt;</mtext>'),
        (r"\text{<img src=x onerror=alert(1)>}", "<mtext>&lt;img"),
        (r"\text{a & b}", "<mtext>a\u00a0&amp;\u00a0b</mtext>"),
        (r"\text{&lt;b&gt;}", "<mtext>&amp;lt;b&amp;gt;</mtext>"),
    ],
)
def test_formula_text_and_arguments_are_escaped(source: str, expected: str) -> None:
    rendered = render_latex_math_to_html(source, display="inline")
    assert rendered.has_error is False
    assert expected in rendered.html
    assert "<b>" not in rendered.html
    assert "<img" not in rendered.html
    # tests/unit/conftest.py fails this call if the pass has to change the renderer's markup.
    sanitize_rendered_html(rendered.html)


def test_formula_arguments_written_into_attributes_are_escaped() -> None:
    rendered = render_latex_math_to_html(r"\textcolor{<b>}{x}", display="inline")
    assert rendered.has_error is False
    assert '<mstyle mathcolor="&lt;b&gt;">' in rendered.html


def test_symbols_render_as_characters() -> None:
    rendered = render_latex_math_to_html(r"a < b \leq \infty", display="inline")
    assert rendered.html == (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow>'
        "<mi>a</mi><mo>&lt;</mo><mi>b</mi><mo>\u2264</mo><mo>\u221e</mo>"
        "</mrow></math>"
    )
