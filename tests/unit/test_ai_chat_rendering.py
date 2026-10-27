from types import SimpleNamespace

from app.services.ai_chat_rendering import render_ai_chat_markdown_to_html
from app.services.ai_chat_rendering import render_ai_chat_streaming_markdown_to_html
from app.services.ai_chat_rendering import sanitize_ai_chat_markdown_citations
from app.services.ai_chat_rendering import find_note_citation_ids
from app.services.ai_chat_rendering import strip_note_citations_for_history
from app.services.agent.web_evidence import WebCitationReference


NOTE_ID = "75193dae-9e05-4a4e-94bf-417ffde18957"
SECOND_NOTE_ID = "75ee44d0-7aee-49a4-935a-a059b02c4bb4"
ROOT_NOTE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ROOT_NOTE_ID = "22222222-2222-4222-8222-222222222222"
MISSING_ID = "99999999-9999-4999-9999-999999999999"
WEB_ID = "33333333-3333-4333-8333-333333333333"
WEB_LINK_ID = "44444444-4444-4444-8444-444444444444"


def _web_evidence() -> WebCitationReference:
    return WebCitationReference(
        evidence_id=WEB_ID,
        final_url="https://example.com/article",
        title="Example article",
        source_kind="opened_page",
        source_page_evidence_id=WEB_ID,
    )


class FakeNotes:
    def has_note(self, note_id: str) -> bool:
        return note_id in {
            ROOT_NOTE_ID,
            OTHER_ROOT_NOTE_ID,
            NOTE_ID,
            SECOND_NOTE_ID,
        }

    def get_note(self, note_id: str):
        if note_id == ROOT_NOTE_ID:
            return SimpleNamespace(
                id=ROOT_NOTE_ID,
                parent_id=None,
                content="<h1>Incorporate AI</h1>",
                tags="architecture",
            )
        if note_id == OTHER_ROOT_NOTE_ID:
            return SimpleNamespace(
                id=OTHER_ROOT_NOTE_ID,
                parent_id=None,
                content="<h1>Other architecture decision</h1>",
                tags="architecture",
            )
        if note_id == NOTE_ID:
            return SimpleNamespace(
                id=NOTE_ID,
                parent_id=ROOT_NOTE_ID,
                content="<h1>Instructor + LiteLLM vs. Pydantic AI</h1><p>Details</p>",
                tags="architecture",
            )
        assert note_id == SECOND_NOTE_ID
        return SimpleNamespace(
            id=SECOND_NOTE_ID,
            parent_id=ROOT_NOTE_ID,
            content="<h1>Pydantic AI might be useful later</h1>",
            tags="architecture",
        )


def test_ai_chat_renderer_moves_bare_note_uuid_to_references_section() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"See note {NOTE_ID} for details.",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert f">{NOTE_ID}<" not in rendered
    assert (
        '<span class="ai-chat-note-mention">'
        "“Instructor + LiteLLM vs. Pydantic AI”</span>"
    ) in rendered
    body_html, references_html = rendered.split('<section class="ai-chat-references"')
    assert 'class="note-reference-link"' not in body_html
    assert 'aria-label="References"' in references_html
    assert '<details class="ai-chat-references-disclosure">' in references_html
    assert (
        '<summary class="ai-chat-references-heading">References</summary>'
        in references_html
    )
    assert '<details class="ai-chat-references-disclosure" open' not in references_html
    assert 'class="ai-chat-note-reference note-reference-block' in rendered
    assert f'data-ref-note-id="{ROOT_NOTE_ID}"' in rendered
    assert 'class="note-reference-link"' in rendered
    assert "Incorporate AI" in references_html


def test_ai_chat_renderer_mentions_explicit_reference_without_leaving_brackets() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Source: [[{NOTE_ID}]]",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert "[[" not in rendered
    assert "]]" not in rendered
    assert '<sup class="ai-chat-citation-marker"' in rendered
    assert 'class="ai-chat-citation-link note-reference-link"' in rendered
    assert f'data-ref-note-id="{ROOT_NOTE_ID}"' in rendered
    assert ">[1]</a></sup>" in rendered
    assert f'data-ref-query="{NOTE_ID}"' in rendered
    assert rendered.count('class="note-reference-link"') == 1


def test_ai_chat_renderer_hides_partial_bracketed_citation_during_streaming() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Supported finding. [[{NOTE_ID}]",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert "Supported finding." in rendered
    assert NOTE_ID not in rendered
    assert "Instructor + LiteLLM" not in rendered
    assert 'class="ai-chat-note-mention"' not in rendered
    assert 'class="ai-chat-citation-marker"' not in rendered
    assert 'class="ai-chat-references"' not in rendered


def test_ai_chat_renderer_hides_partial_link_text_citation_during_streaming() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Supported finding. [[{NOTE_ID}|the pla",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
        allowed_web_evidence=(),
    )

    assert "Supported finding." in rendered
    assert NOTE_ID not in rendered
    assert "the pla" not in rendered


def test_ai_chat_citation_with_link_text_cites_its_note() -> None:
    # [[UUID|text]] is the same reference as [[UUID]] (docs/ui/references.md, "Link text").
    markdown = f"Supported finding. [[{NOTE_ID}|the plan]]"
    rendered = render_ai_chat_markdown_to_html(
        markdown, notes=FakeNotes(), allowed_note_ids=(NOTE_ID,), allowed_web_evidence=(),
    )

    assert find_note_citation_ids(markdown, notes=FakeNotes()) == (NOTE_ID,)
    assert 'class="ai-chat-citation-marker"' in rendered
    assert "|the plan" not in rendered
    assert strip_note_citations_for_history(markdown) == "Supported finding."


def test_ai_chat_streaming_renderer_withholds_all_reference_ui_until_done() -> None:
    rendered = render_ai_chat_streaming_markdown_to_html(
        (
            "1. Supported finding. "
            f"[[{NOTE_ID}]]\n\n"
            f"- **Source:** [Saved note](https://example.com) [[{NOTE_ID}]]"
        ),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert "Supported finding." in rendered
    assert NOTE_ID not in rendered
    assert "Saved note" not in rendered
    assert "example.com" not in rendered
    assert 'class="ai-chat-citation-marker"' not in rendered
    assert 'class="ai-chat-references"' not in rendered


def test_ai_chat_renderer_deduplicates_repeated_reference_links() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Compare [[{NOTE_ID}]] with {NOTE_ID}.",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert rendered.count('class="ai-chat-note-mention"') == 1
    assert rendered.count('class="ai-chat-citation-marker"') == 1
    assert rendered.count('class="note-reference-link"') == 1
    assert 'class="ai-chat-open-all-references"' not in rendered


def test_ai_chat_renderer_collapses_adjacent_duplicate_citation_markers() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Supported claim. [[{NOTE_ID}]][[{NOTE_ID}]]",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert rendered.count('class="ai-chat-citation-marker"') == 1
    assert rendered.count(">[1]</a></sup>") == 1
    assert f'data-ref-query="{NOTE_ID}"' in rendered


def test_ai_chat_renderer_collapses_adjacent_same_root_citation_markers() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Supported claim. [[{NOTE_ID}]] [[{SECOND_NOTE_ID}]]",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID, SECOND_NOTE_ID),
    allowed_web_evidence=(),
    )

    expected_query = f"{NOTE_ID} OR {SECOND_NOTE_ID}"
    assert rendered.count('class="ai-chat-citation-marker"') == 1
    assert rendered.count(">[1]</a></sup>") == 1
    assert rendered.count(f'data-ref-query="{expected_query}"') == 2


def test_ai_chat_renderer_sorts_adjacent_citations_by_reference_number() -> None:
    rendered = render_ai_chat_markdown_to_html(
        (
            f"First source [[{ROOT_NOTE_ID}]]. "
            f"Second source [[{OTHER_ROOT_NOTE_ID}]]. "
            f"Combined [[{OTHER_ROOT_NOTE_ID}]][[{ROOT_NOTE_ID}]]."
        ),
        notes=FakeNotes(),
        allowed_note_ids=(ROOT_NOTE_ID, OTHER_ROOT_NOTE_ID),
    allowed_web_evidence=(),
    )

    body_html, _references_html = rendered.split('<section class="ai-chat-references"')
    combined_html = body_html.split("Combined ", maxsplit=1)[1]
    assert combined_html.index(">[1]</a></sup>") < combined_html.index(">[2]</a></sup>")


def test_ai_chat_renderer_adds_open_all_link_with_or_query_for_multiple_refs() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Compare [[{NOTE_ID}]] and [[{OTHER_ROOT_NOTE_ID}]].",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID, OTHER_ROOT_NOTE_ID),
    allowed_web_evidence=(),
    )

    expected_query = f"{NOTE_ID} OR {OTHER_ROOT_NOTE_ID}"
    assert rendered.count('class="note-reference-link"') == 2
    assert 'class="ai-chat-open-all-references"' in rendered
    assert f'data-ref-query="{expected_query}"' in rendered
    assert ">Open all references</a>" in rendered


def test_ai_chat_renderer_groups_child_citations_into_one_root_reference() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Compare [[{NOTE_ID}]] and [[{SECOND_NOTE_ID}]].",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID, SECOND_NOTE_ID),
    allowed_web_evidence=(),
    )

    assert 'class="ai-chat-note-mention"' not in rendered
    assert rendered.count('class="ai-chat-citation-marker"') == 2
    assert rendered.count('class="note-reference-link"') == 1
    assert rendered.count(">[1]</a></sup>") == 2
    assert f'data-ref-note-id="{ROOT_NOTE_ID}"' in rendered
    expected_query = f"{NOTE_ID} OR {SECOND_NOTE_ID}"
    assert f'data-ref-query="{expected_query}"' in rendered
    assert 'class="ai-chat-open-all-references"' not in rendered


def test_ai_chat_renderer_recovers_known_uuid_from_inline_code_and_unicode_dashes() -> None:
    for dash_character in "-‐‑‒–—−":
        unicode_dash_note_id = SECOND_NOTE_ID.replace("-", dash_character)
        rendered = render_ai_chat_markdown_to_html(
            f"The note with the ID `{unicode_dash_note_id}` discusses Pydantic AI.",
            notes=FakeNotes(),
            allowed_note_ids=(SECOND_NOTE_ID,),
        allowed_web_evidence=(),
        )

        assert f">{unicode_dash_note_id}<" not in rendered
        assert "Pydantic AI might be useful later" in rendered
        assert rendered.count('class="ai-chat-note-mention"') == 1
        assert rendered.count('class="note-reference-link"') == 1
        assert f'data-ref-note-id="{ROOT_NOTE_ID}"' in rendered


def test_ai_chat_renderer_suppresses_unknown_citations_but_preserves_fenced_code() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Unknown {MISSING_ID}.\n\n```text\n{NOTE_ID}\n```",
        notes=FakeNotes(),
        allowed_note_ids=(),
    allowed_web_evidence=(),
    )

    assert MISSING_ID not in rendered
    assert NOTE_ID in rendered
    assert "<pre>" in rendered
    assert 'class="note-reference-link"' not in rendered
    assert 'class="ai-chat-references"' not in rendered


def test_ai_chat_sanitizer_removes_hallucinated_uuid_citations() -> None:
    sanitized = sanitize_ai_chat_markdown_citations(
        f"A grounded sentence. [[{MISSING_ID}]]",
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert sanitized == "A grounded sentence."


def test_ai_chat_renderer_suppresses_note_citations_not_retrieved_in_current_run() -> None:
    rendered = render_ai_chat_markdown_to_html(
        f"Bayes' theorem needs no saved notes. [[{NOTE_ID}]] `{SECOND_NOTE_ID}`",
        notes=FakeNotes(),
        allowed_note_ids=(),
    allowed_web_evidence=(),
    )

    assert "Bayes' theorem needs no saved notes." in rendered
    assert NOTE_ID not in rendered
    assert SECOND_NOTE_ID not in rendered
    assert "Instructor + LiteLLM" not in rendered
    assert "Pydantic AI" not in rendered
    assert 'class="ai-chat-note-mention"' not in rendered
    assert 'class="ai-chat-references"' not in rendered


def test_ai_chat_renderer_maps_numbered_citations_to_superscript_references() -> None:
    rendered = render_ai_chat_markdown_to_html(
        "First supported claim[citation:1] and second supported claim[citation:2].",
        notes=FakeNotes(),
        allowed_note_ids=(ROOT_NOTE_ID, OTHER_ROOT_NOTE_ID),
    allowed_web_evidence=(),
    )

    assert rendered.count('class="ai-chat-citation-marker"') == 2
    assert ">[1]</a></sup>" in rendered
    assert ">[2]</a></sup>" in rendered
    assert rendered.count('class="ai-chat-reference-number"') == 2
    assert rendered.count('class="note-reference-link"') == 2


def test_ai_chat_renderer_keeps_loose_cited_items_in_one_ordered_list() -> None:
    rendered = render_ai_chat_markdown_to_html(
        (
            "1. **Launch Date:** March 17, 2042.\n"
            "   [citation:1]\n\n"
            "2. **Launch Color:** Ultraviolet.\n"
            "   [citation:2]"
        ),
        notes=FakeNotes(),
        allowed_note_ids=(ROOT_NOTE_ID, OTHER_ROOT_NOTE_ID),
    allowed_web_evidence=(),
    )

    body_html, references_html = rendered.split('<section class="ai-chat-references"')
    assert body_html.count("<ol>") == 1
    assert body_html.count("<li>") == 2
    assert body_html.count('class="ai-chat-citation-marker"') == 2
    assert references_html.count('class="ai-chat-reference-number"') == 2


def test_ai_chat_sanitizer_canonicalizes_authorized_numbered_citations() -> None:
    sanitized = sanitize_ai_chat_markdown_citations(
        "First supported claim[citation:1].",
        notes=FakeNotes(),
        allowed_note_ids=(ROOT_NOTE_ID,),
    allowed_web_evidence=(),
    )

    assert sanitized == f"First supported claim[[{ROOT_NOTE_ID}]]."


def test_ai_chat_renderer_removes_standalone_source_lines_and_repairs_numbering() -> None:
    markdown = (
        "1. **Exercise:** Farmer's walks strengthen the core.\n\n"
        f"- **Source:** [YouTube Video](https://example.com/one) [[{NOTE_ID}]]\n\n"
        "1. **Exercise snacks:** Short workouts support muscle mass.\n\n"
        f"- **Source:** [YouTube Video](https://example.com/two) [[{SECOND_NOTE_ID}]]"
    )

    sanitized = sanitize_ai_chat_markdown_citations(
        markdown,
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID, SECOND_NOTE_ID),
    allowed_web_evidence=(),
    )
    rendered = render_ai_chat_markdown_to_html(
        sanitized,
        notes=FakeNotes(),
        allowed_note_ids=(NOTE_ID, SECOND_NOTE_ID),
    allowed_web_evidence=(),
    )

    assert "Source:" not in sanitized
    assert "YouTube Video" not in sanitized
    assert "example.com" not in sanitized
    assert f"walks strengthen the core. [[{NOTE_ID}]]" in sanitized
    assert f"workouts support muscle mass. [[{SECOND_NOTE_ID}]]" in sanitized
    body_html, _references_html = rendered.split('<section class="ai-chat-references"')
    assert "YouTube Video" not in body_html
    assert "example.com" not in body_html
    assert body_html.count('<sup class="ai-chat-citation-marker"') == 2
    assert body_html.count("<ol>") == 1
    assert body_html.count("<li>") == 2


def test_ai_chat_renderer_sanitizes_and_renders_web_citation() -> None:
    evidence = _web_evidence()
    sanitized = sanitize_ai_chat_markdown_citations(
        f"Fresh claim [[web:{WEB_ID}]] and hidden [[web:{MISSING_ID}]].",
        notes=FakeNotes(),
        allowed_note_ids=(),
        allowed_web_evidence=(evidence,),
    )
    rendered = render_ai_chat_markdown_to_html(
        sanitized,
        notes=FakeNotes(),
        allowed_note_ids=(),
        allowed_web_evidence=(evidence,),
    )

    assert sanitized == f"Fresh claim [[web:{WEB_ID}]] and hidden ."
    assert 'href="https://example.com/article"' in rendered
    assert 'target="_blank" rel="noopener noreferrer"' in rendered
    assert "Example article" in rendered
    assert MISSING_ID not in rendered


def test_ai_chat_renderer_uses_observed_page_link_as_reference_target() -> None:
    reference = WebCitationReference(
        evidence_id=WEB_LINK_ID,
        final_url="https://articles.example/specific-story",
        title="Specific story",
        source_kind="page_link",
        source_page_evidence_id=WEB_ID,
    )

    rendered = render_ai_chat_markdown_to_html(
        f"The list includes Specific story. [[web:{WEB_LINK_ID}]]",
        notes=FakeNotes(),
        allowed_note_ids=(),
        allowed_web_evidence=(reference,),
    )

    assert 'href="https://articles.example/specific-story"' in rendered
    assert "Specific story" in rendered


def test_ai_chat_renderer_preserves_bold_currency_with_web_citation() -> None:
    evidence = _web_evidence()
    rendered = render_ai_chat_markdown_to_html(
        (
            "QQQ is currently **$741.64**, up **$0.43** "
            f"(**+0.06%**) today. [[web:{WEB_ID}]]"
        ),
        notes=FakeNotes(),
        allowed_note_ids=(),
        allowed_web_evidence=(evidence,),
    )

    assert "<strong>$741.64</strong>" in rendered
    assert "<strong>$0.43</strong>" in rendered
    assert "<strong>+0.06%</strong>" in rendered
    assert "meta-latex" not in rendered
    assert 'class="ai-chat-references"' in rendered


def test_streaming_renderer_hides_web_citation_tokens() -> None:
    evidence = _web_evidence()
    rendered = render_ai_chat_streaming_markdown_to_html(
        f"Fresh claim [[web:{WEB_ID}]]",
        allowed_note_ids=(),
        allowed_web_evidence=(evidence,),
    )

    assert "Fresh claim" in rendered
    assert WEB_ID not in rendered
