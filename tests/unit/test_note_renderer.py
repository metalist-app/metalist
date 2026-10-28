from __future__ import annotations

from types import SimpleNamespace


from app.presentation.render.note_renderer import render_read_only_mode


def test_a_saved_chat_answer_keeps_its_chat_html_exactly() -> None:
    completed_chat_html = (
        '<div class="ai-chat-message-content meta-markdown" '
        'data-markdown-rendered="true">'
        '<h1>Result</h1>'
        '<p>Supported claim'
        '<sup class="ai-chat-citation-marker" aria-label="Reference 1">'
        '<a href="#" class="ai-chat-citation-link note-reference-link" '
        'data-ref-note-id="75193dae-9e05-4a4e-94bf-417ffde18957" '
        'data-ref-query="75193dae-9e05-4a4e-94bf-417ffde18957">[1]</a>'
        '</sup>.</p>'
        '<details class="ai-chat-references-disclosure"></details>'
        '</div>'
    )
    note = SimpleNamespace(content=completed_chat_html, tags="@ai")

    assert render_read_only_mode(note) == completed_chat_html


def test_a_markdown_chat_answer_is_drawn_as_chat_html() -> None:
    note = SimpleNamespace(
        content="<div># Prior copy</div><div></div><div>Body text</div>",
        tags="@markdown @ai",
    )

    assert render_read_only_mode(note) == (
        '<div class="ai-chat-message-content meta-markdown" '
        'data-markdown-rendered="true">'
        '<h1>Prior copy</h1><p>Body text</p>'
        '</div>'
    )


def test_a_note_tagged_ai_by_hand_copies_as_an_ordinary_note() -> None:
    # "Ideas for using AI at work", tagged @ai in its tag bar: not a saved chat answer, so
    # it copies like any other note, comments left out (agreed 2026-10-28).
    content = "<div>Ideas for using AI at work /* draft */</div>"
    plain = render_read_only_mode(SimpleNamespace(content=content, tags=""))

    assert render_read_only_mode(SimpleNamespace(content=content, tags="@ai")) == plain
