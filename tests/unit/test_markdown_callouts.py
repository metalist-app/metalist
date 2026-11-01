"""Callouts in a Markdown note (docs/ui/content-formatting.md, Callouts; agreed 2026-10-31):
a quote whose first line is [!type] is led by its type and title in bold; one marked - or +
folds, and a click on its title writes the other mark into the note's text."""

from __future__ import annotations

import pytest

import app.usecases.toggle_markdown_task as module
from app.services.input_errors import InputRejected
from app.services.markdown_rendering import markdown_callout_lines, render_markdown_to_html, render_note_markdown
from app.services.markdown_tasks import toggle_callout_fold_in_note_html


def note_html(markdown: str) -> str:
    return render_note_markdown(markdown, takes_footnotes=True).html


@pytest.mark.parametrize(("markdown", "expected"), [
    (
        "> [!warning] Watch **out**\n> body",
        '<blockquote class="meta-markdown-callout"><p><strong>Warning: Watch <strong>out</strong></strong></p>'
        "<p>body</p></blockquote>",
    ),
    # No title: the type alone, capitalised whatever its case.
    ("> [!note]\n> body", '<blockquote class="meta-markdown-callout"><p><strong>Note</strong></p><p>body</p></blockquote>'),
    ("> [!TODO] x", '<blockquote class="meta-markdown-callout"><p><strong>Todo: x</strong></p></blockquote>'),
    # A blank line (no >) ends a callout; an ordinary quote is unchanged.
    (
        "> [!tip] a\n\n> plain",
        '<blockquote class="meta-markdown-callout"><p><strong>Tip: a</strong></p></blockquote>'
        "<blockquote><p>plain</p></blockquote>",
    ),
    ("> plain\n> [!note] later", "<blockquote><p>plain\n[!note] later</p></blockquote>"),
])
def test_a_callout_is_a_quote_led_by_its_type_and_title(markdown: str, expected: str) -> None:
    assert note_html(markdown) == expected


def test_a_folding_callout_is_numbered_and_starts_as_marked() -> None:
    markdown = "Intro\n> [!tip]- Folded\n> hidden\n> > [!faq]+ Open\n> > inner\n\n> [!note] fixed"
    rendered = note_html(markdown)
    assert '<details class="meta-markdown-callout-fold" data-callout-index="0"><summary><strong>Tip: Folded' in rendered
    assert '<details class="meta-markdown-callout-fold" data-callout-index="1" open=""><summary><strong>Faq: Open' in rendered
    assert rendered.count("<details") == 2
    assert markdown_callout_lines(markdown) == [1, 3]


def test_a_callouts_body_is_markdown_with_its_task_lines_kept() -> None:
    markdown = "> [!todo]- List\n> - [ ] milk\n> see [[11111111-1111-4111-8111-111111111111]]"
    rendered = note_html(markdown)
    assert 'data-task-index="0"' in rendered
    assert render_note_markdown(markdown, takes_footnotes=True).html.count("<li") == 1


def test_the_ai_chat_draws_callouts_without_numbers() -> None:
    rendered = render_markdown_to_html("> [!tip]+ T\n> b")
    assert '<details class="meta-markdown-callout-fold" open="">' in rendered
    assert "data-callout-index" not in rendered


NOTE = (
    "<div>&gt; [!tip]- <b>Packing</b></div><div>&gt; body</div><div>&gt; &gt;&nbsp;[!faq]+ Inner</div>"
    "<div><br></div><div>&gt; [!note] fixed</div><div><br></div><div>&gt; [!todo]+ last</div>"
)


@pytest.mark.parametrize(("callout_index", "is_open", "before", "after"), [
    (0, True, "[!tip]- <b>", "[!tip]+ <b>"),
    (1, False, "[!faq]+ Inner", "[!faq]- Inner"),
    # [!note] has no mark and is not numbered.
    (2, False, "[!todo]+ last", "[!todo]- last"),
])
def test_a_title_click_changes_only_its_mark(callout_index: int, is_open: bool, before: str, after: str) -> None:
    toggled = toggle_callout_fold_in_note_html(content_html=NOTE, callout_index=callout_index, is_open=is_open)
    assert toggled == NOTE.replace(before, after)


@pytest.mark.parametrize(("callout_index", "is_open"), [(0, False), (1, True), (3, True)])
def test_a_note_changed_under_the_title_is_refused(callout_index: int, is_open: bool) -> None:
    with pytest.raises(InputRejected, match="try the title again"):
        toggle_callout_fold_in_note_html(content_html=NOTE, callout_index=callout_index, is_open=is_open)


class _Record:
    def __init__(self, content: str, tags: str):
        self.content = content
        self.tags = tags


@pytest.mark.parametrize("tags", ["@markdown", "trip"])
def test_a_title_click_saves_one_undo_step_in_a_markdown_note(monkeypatch: pytest.MonkeyPatch, tags: str) -> None:
    record = _Record("<div>&gt; [!tip]- T</div>", tags)
    saved: list = []
    undo: list = []
    monkeypatch.setattr(module, "store", type("Store", (), {"get": staticmethod(lambda note_id: record)})())
    monkeypatch.setattr(module, "apply_update_content", lambda note_id, content, tags, token: saved.append(content))
    monkeypatch.setattr(module.undo_state, "record_update", lambda *args, **kwargs: undo.append(kwargs))
    command = module.CmdToggleMarkdownCallout(
        note_id="n", callout_index=0, is_open=True, token="t", client_id="c", undo_context="u", viewport={},
    )
    if tags == "trip":
        with pytest.raises(InputRejected, match="no longer Markdown"):
            command.execute()
        assert saved == [] and undo == []
        return
    command.execute()
    assert saved == ["<div>&gt; [!tip]+ T</div>"]
    assert [(step["before"], step["after"]) for step in undo] == [(record.content, saved[0])]
