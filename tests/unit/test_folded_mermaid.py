"""A folded note that opens with a Mermaid diagram draws the whole diagram (docs/ui/content-formatting.md)."""

from __future__ import annotations

import pytest

from app.services.credential_display import CredentialDisplay
from app.services.embedded_references import EmbedRenderContext, render_collapsed_note_content_with_embeds

NOTE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_SOURCE_LINE = "A --&gt; B"


def _folded(lines: list[str], tags: str) -> str:
    context = EmbedRenderContext(
        has_note=lambda note_id: False, get_note=lambda note_id: None, get_children=lambda parent_id: [],
        has_file=lambda file_id: False, get_file=lambda file_id: None,
        is_property_used=lambda property_name: False, is_shown_in_gallery=lambda gallery_note_id, note_id: True, static_collapse_arrows=False,
    )
    return render_collapsed_note_content_with_embeds(
        note_id=NOTE_ID, content_html="".join(f"<div>{line}</div>" for line in lines), tags=tags,
        context=context, static_export=False, credentials=CredentialDisplay.DOTS,
    )


@pytest.mark.parametrize(
    ("lines", "tags"),
    [
        (["graph TD", SECOND_SOURCE_LINE], "@mermaid"),
        (["((graph TD", f"{SECOND_SOURCE_LINE}))", "After"], "((@mermaid))"),
        (["```mermaid", "graph TD", SECOND_SOURCE_LINE, "```", "After"], "@markdown"),
    ],
)
def test_a_note_opening_with_a_diagram_keeps_the_whole_diagram(lines: list[str], tags: str) -> None:
    rendered = _folded(lines, tags)
    assert "meta-mermaid-source" in rendered
    assert SECOND_SOURCE_LINE in rendered


@pytest.mark.parametrize(
    ("lines", "tags"),
    [
        (["Before", "((graph TD", f"{SECOND_SOURCE_LINE}))"], "((@mermaid))"),
        (["Intro", "```mermaid", "graph TD", SECOND_SOURCE_LINE, "```"], "@markdown"),
        (["Mermaid is a fish", "second line"], ""),
    ],
)
def test_a_note_opening_with_text_keeps_only_its_first_line(lines: list[str], tags: str) -> None:
    rendered = _folded(lines, tags)
    assert lines[0] in rendered
    assert "meta-mermaid-source" not in rendered
    assert lines[1] not in rendered
