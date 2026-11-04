"""HTML inside Markdown (2026-10-31; docs/ui/content-formatting.md, Markdown meta tags): a
note's Markdown keeps the HTML written in it as the standard does, each tag kept or dropped
by the stored-note policy that pasted HTML follows; the AI chat's replies show it as text."""

from __future__ import annotations

import pytest

from app.services.credential_display import CredentialDisplay
from app.services.content_formatting import format_note_content_for_view
from app.services.input_errors import InputRejected
from app.services.markdown_rendering import markdown_fold_states, render_markdown_to_html, render_note_markdown
from app.services.markdown_tasks import toggle_html_fold_in_note_html


def note_html(markdown: str) -> str:
    return render_note_markdown(markdown, takes_footnotes=True).html


@pytest.mark.parametrize(("markdown", "expected"), [
    # 1. Tags the policy keeps; one it doesn't goes, its text stays.
    ("H<sub>2</sub>O x<sup>2</sup> <u>u</u> <mark>m</mark>", "<p>H<sub>2</sub>O x<sup>2</sup> <u>u</u> <mark>m</mark></p>"),
    ("<kbd>Ctrl</kbd>", "<p>Ctrl</p>"),
    # 2. Markdown around and inside tags.
    ("<u>**bold** under</u>", "<p><u><strong>bold</strong> under</u></p>"),
    # 4. Attributes and styles off the policy go, colours included.
    ('<span style="color:red" onclick="x()">plain</span>', "<p><span>plain</span></p>"),
    ('<span style="font-weight: bold">kept</span>', '<p><span style="font-weight:bold">kept</span></p>'),
    # 5. A tag dropped with its content.
    ("a<script>alert(1)</script>b", "<p>ab</p>"),
    ("a<iframe src=\"https://e.com\">x</iframe>b", "<p>ab</p>"),
    # 6. Links: web, mail and phone addresses only.
    ('<a href="https://e.com">ok</a> <a href="javascript:alert(1)">no</a>', '<p><a href="https://e.com">ok</a> <a>no</a></p>'),
    # 7. Comments are hidden.
    ("a <!-- hidden --> b", "<p>a  b</p>"),
    # 8. Code, and a lone <, stay as written.
    ("`<u>x</u>` and a < b", "<p><code>&lt;u&gt;x&lt;/u&gt;</code> and a &lt; b</p>"),
    # Autolinks and emphasis never reach inside a tag.
    ('A <img src="https://e.com/a_b_c.png" alt="x*y*z">', '<p>A <img src="https://e.com/a_b_c.png" alt="x*y*z"></p>'),
])
def test_inline_html_is_kept_as_pasted_html_is(markdown: str, expected: str) -> None:
    assert note_html(markdown) == expected


def test_an_html_block_runs_to_a_blank_line_with_markdown_after_it() -> None:
    # 3. CommonMark: the block's lines are HTML; the Markdown between blocks renders.
    markdown = "<details>\n<summary>Open</summary>\n\n- **inside**\n\n</details>\n\nAfter"
    assert note_html(markdown) == (
        '<details class="meta-markdown-html-fold" data-fold-index="0">\n<summary>Open</summary>'
        "<ul><li><strong>inside</strong></li></ul></details><p>After</p>"
    )


def test_a_raw_block_runs_to_its_closing_tag() -> None:
    # As in any HTML, a line break right after <pre> is not part of it.
    assert note_html("<pre>\n  *not* emphasis\n\n  still pre\n</pre>\nAfter") == (
        "<pre>  *not* emphasis\n\n  still pre\n</pre><p>After</p>"
    )
    assert note_html("<!-- a\n\ncomment -->\nShown") == "<p>Shown</p>"


def test_an_unclosed_tag_ends_with_the_note() -> None:
    # 10. Closed where the note ends, footnote text too.
    assert note_html("open <u>here") == "<p>open <u>here</u></p>"
    footnotes = render_note_markdown("A[^1]\n\n[^1]: <b>bold", takes_footnotes=True).footnotes
    assert [body for _token, body in footnotes] == ["<b>bold</b>"]


def test_formulas_keep_their_text_and_the_ai_chat_shows_html_as_text() -> None:
    # 9. The AI chat's replies are not the user's HTML.
    assert render_markdown_to_html("<u>x</u>") == "<p>&lt;u&gt;x&lt;/u&gt;</p>"
    shown = format_note_content_for_view(
        content_html="<div>$\\text{&lt;b&gt;x&lt;/b&gt;}$ and &lt;u&gt;y&lt;/u&gt;</div>",
        tags="@markdown",
        credentials=CredentialDisplay.DOTS,
    )
    assert "<mtext>&lt;b&gt;x&lt;/b&gt;</mtext>" in shown
    assert "<u>y</u>" in shown


def test_a_markdown_region_inside_another_note_keeps_html_too() -> None:
    shown = format_note_content_for_view(
        content_html="<div>x ((&lt;u&gt;under&lt;/u&gt;))</div>", tags="((@markdown))", credentials=CredentialDisplay.DOTS,
    )
    assert "<u>under</u>" in shown


# A <details> fold's title (agreed 2026-10-31): a click adds or removes its open attribute in
# the note's text, and only that fold's; one in code is never touched.
FOLDS = (
    "<div>`&lt;details&gt;` in code</div><div>&lt;details&gt;</div><div>&lt;summary&gt;A&lt;/summary&gt;</div>"
    "<div><br></div><div>in A</div><div><br></div><div>&lt;/details&gt;</div><div><br></div>"
    '<div>&lt;details open class="x"&gt;&lt;summary&gt;B&lt;/summary&gt;b&lt;/details&gt;</div>'
)


def test_folds_are_numbered_with_their_state() -> None:
    assert markdown_fold_states("<details>\n<summary>A</summary>\n\n</details>\n\n`<details>`\n\n<details open>x</details>") == [
        False, True,
    ]


@pytest.mark.parametrize(("fold_index", "is_open", "before", "after"), [
    (0, True, "<div>&lt;details&gt;</div>", "<div>&lt;details open&gt;</div>"),
    (1, False, '&lt;details open class="x"&gt;', '&lt;details class="x"&gt;'),
])
def test_a_fold_title_click_changes_only_its_open_attribute(fold_index: int, is_open: bool, before: str, after: str) -> None:
    toggled = toggle_html_fold_in_note_html(content_html=FOLDS, fold_index=fold_index, is_open=is_open)
    assert toggled == FOLDS.replace(before, after)
    assert "`&lt;details&gt;` in code" in toggled


@pytest.mark.parametrize(("fold_index", "is_open"), [(0, False), (1, True), (2, True)])
def test_a_note_changed_under_the_fold_is_refused(fold_index: int, is_open: bool) -> None:
    with pytest.raises(InputRejected, match="try the title again"):
        toggle_html_fold_in_note_html(content_html=FOLDS, fold_index=fold_index, is_open=is_open)
