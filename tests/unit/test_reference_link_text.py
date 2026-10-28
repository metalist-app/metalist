"""Link text: [[UUID|shown text]] (agreed 2026-10-27, docs/ui/references.md, "Link text").

KYOTO is a note ("Kyoto trip", with a second line); MAP is a file (map.png); NOTE_N is a
note whose first line holds link text.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Dict

from app.services.backlinks import _extract_preview as backlink_first_line_preview
from app.services.embedded_references import (
    EmbedRenderContext,
    collect_active_reference_tokens,
    first_line_preview,
    render_collapsed_note_content_with_embeds,
    render_note_content_with_embeds,
    text_with_references_as_words,
)
from app.services.file_registry import referenced_file_ids

HOST_ID = "11111111-1111-4111-8111-111111111111"
KYOTO_ID = "22222222-2222-4222-8222-222222222222"
MAP_ID = "33333333-3333-4333-8333-333333333333"
NOTE_N_ID = "44444444-4444-4444-8444-444444444444"


def _context(*, kyoto_first_line: str) -> EmbedRenderContext:
    notes: Dict[str, SimpleNamespace] = {
        KYOTO_ID: SimpleNamespace(
            id=KYOTO_ID, content=f"<div>{kyoto_first_line}</div><div>3 nights</div>", tags="", is_collapsed=False,
        ),
        NOTE_N_ID: SimpleNamespace(
            id=NOTE_N_ID, content=f"<div>See [[{KYOTO_ID}|the plan]]</div>", tags="", is_collapsed=False,
        ),
    }
    files = {
        MAP_ID: SimpleNamespace(
            id=MAP_ID, title="map.png", original_filename="map.png", mime_type="image/png",
            size_bytes=2048, thumbnail_kind="image", content_revision=1,
        ),
    }
    return EmbedRenderContext(
        has_note=lambda note_id: note_id in notes,
        get_note=lambda note_id: notes[note_id],
        get_children=lambda parent_id: [],
        has_file=lambda file_id: file_id in files,
        get_file=lambda file_id: files[file_id],
        is_property_used=lambda property_name: False,
        static_collapse_arrows=False,
    )


def _render(content_html: str, context: EmbedRenderContext) -> str:
    return render_note_content_with_embeds(
        note_id=HOST_ID, content_html=content_html, tags="", context=context,
        static_export=False, redact_credentials=False,
    )


def _visible_text(rendered: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", rendered).split())


def test_1_link_text_shows_instead_of_the_first_line() -> None:
    rendered = _render(f"<div>See [[{KYOTO_ID}|the plan]] tonight</div>", _context(kyoto_first_line="Kyoto trip"))
    assert _visible_text(rendered) == "See the plan tonight"
    assert f'data-ref-note-id="{KYOTO_ID}"' in rendered
    assert "note-reference-link-mode" in rendered


def test_2_link_text_stays_when_the_first_line_changes() -> None:
    rendered = _render(f"<div>See [[{KYOTO_ID}|the plan]] tonight</div>", _context(kyoto_first_line="Osaka trip"))
    assert _visible_text(rendered) == "See the plan tonight"


def test_3_a_plain_link_still_shows_the_first_line() -> None:
    assert _visible_text(_render(f"<div>[[{KYOTO_ID}]]</div>", _context(kyoto_first_line="Kyoto trip"))) == "Kyoto trip"


def test_4_text_after_the_first_bar_keeps_its_bars() -> None:
    assert _visible_text(_render(f"<div>[[{KYOTO_ID}|a|b]]</div>", _context(kyoto_first_line="Kyoto trip"))) == "a|b"


def test_5_html_in_link_text_is_shown_as_text() -> None:
    # The editor stores typed angle brackets as entities; they stay text.
    rendered = _render(f"<div>[[{KYOTO_ID}|&lt;b&gt;x&lt;/b&gt;]]</div>", _context(kyoto_first_line="Kyoto trip"))
    assert "<b>x</b>" not in rendered
    assert "&lt;b&gt;x&lt;/b&gt;" in rendered


def test_6_empty_link_text_is_not_a_reference() -> None:
    content = f"<div>[[{KYOTO_ID}|]]</div>"
    rendered = _render(content, _context(kyoto_first_line="Kyoto trip"))
    assert "note-reference-block" not in rendered
    assert _visible_text(rendered) == f"[[{KYOTO_ID}|]]"
    assert collect_active_reference_tokens(content) == []


def test_7_a_note_that_is_only_link_text_is_a_link() -> None:
    rendered = _render(f"<div>[[{KYOTO_ID}|the plan]]</div>", _context(kyoto_first_line="Kyoto trip"))
    assert "note-reference-link-mode" in rendered
    assert "note-embed-block" not in rendered
    assert _visible_text(rendered) == "the plan"


def test_8_link_text_on_a_file() -> None:
    content = f"<div>[[{MAP_ID}|the map]]</div>"
    rendered = _render(content, _context(kyoto_first_line="Kyoto trip"))
    # The file's kind badge, then the link text in place of its name.
    assert _visible_text(rendered) == "IMG the map"
    assert "map.png" not in _visible_text(rendered)
    assert f'data-file-ref-id="{MAP_ID}"' in rendered
    assert referenced_file_ids(content) == [MAP_ID]


def test_9_a_first_line_holding_link_text_reads_with_it() -> None:
    content = f"<div>See [[{KYOTO_ID}|the plan]]</div>"
    assert first_line_preview(content) == "See the plan"
    assert backlink_first_line_preview(content) == "See the plan"
    assert _visible_text(_render(f"<div>[[{NOTE_N_ID}]]</div>", _context(kyoto_first_line="Kyoto trip"))) == "See the plan"


def test_10_a_folded_note_shows_its_link_text() -> None:
    rendered = render_collapsed_note_content_with_embeds(
        note_id=HOST_ID, content_html=f"<div>Plan: [[{KYOTO_ID}|the plan]]</div><div>later</div>",
        tags="", context=_context(kyoto_first_line="Kyoto trip"), static_export=False, redact_credentials=False,
    )
    assert _visible_text(rendered) == "Plan: the plan"


def test_12_an_embed_with_text_is_the_embed() -> None:
    content = f"<div>![[{KYOTO_ID}|the plan]]</div>"
    rendered = _render(content, _context(kyoto_first_line="Kyoto trip"))
    assert "note-embed-block" in rendered
    assert "the plan" not in _visible_text(rendered)
    assert "Kyoto trip" in _visible_text(rendered)


def test_scanners_read_the_uuid_before_the_bar() -> None:
    tokens = collect_active_reference_tokens(f"<div>a [[{KYOTO_ID}|x]] b ![[{MAP_ID}|300]]</div>")
    assert [(token.note_id, token.is_embed, token.link_text) for token in tokens] == [
        (KYOTO_ID, False, "x"), (MAP_ID, True, "300"),
    ]


def test_link_text_cannot_hold_brackets() -> None:
    # A bracket ends the attempt, as for any [[...]] that is not a reference; a
    # reference written inside it is still found.
    tokens = collect_active_reference_tokens(f"<div>[[{KYOTO_ID}|see [[{MAP_ID}]] here]]</div>")
    assert [token.note_id for token in tokens] == [MAP_ID]


def test_words_read_from_a_line_keep_link_text() -> None:
    # The export's default title and the AI's export-title suggestions read words this way.
    text = f"See [[{KYOTO_ID}|the plan]] and [[{KYOTO_ID}]] with ![[{MAP_ID}|300]] [[@LaTeX]]"
    assert " ".join(text_with_references_as_words(text).split()) == "See the plan and with"
