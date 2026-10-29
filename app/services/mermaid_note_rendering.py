"""The @mermaid renderer: the note's text is one Mermaid diagram.

The same source markup a fenced ```mermaid block produces under @markdown, in
its own `meta-mermaid` block (styled in main.css); the browser draws it like a
fenced block (mermaid-render-service.js).
"""
from __future__ import annotations

import html
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import FrozenSet, Iterator

from app.services.structured_note_renderers import _copyable_attr, _extract_plain_text


@dataclass(frozen=True, slots=True)
class FoundDiagram:
    """A Mermaid diagram a render met: its source, and whether it is closed (a fence
    without its closing ``` runs to the note's end and is not)."""

    source: str
    is_closed: bool


# Open while finding_diagrams() lists the diagrams a render meets.
_DIAGRAMS_FOUND: ContextVar[list[FoundDiagram] | None] = ContextVar("diagrams_found", default=None)


@contextmanager
def finding_diagrams() -> Iterator[list[FoundDiagram]]:
    """While open, every Mermaid diagram a render meets is listed, in order, instead of marked."""
    assert _DIAGRAMS_FOUND.get() is None, "finding diagrams does not nest"
    found: list[FoundDiagram] = []
    reset_token = _DIAGRAMS_FOUND.set(found)
    try:
        yield found
    finally:
        _DIAGRAMS_FOUND.reset(reset_token)


def found_diagram(*, source: str, is_closed: bool) -> bool:
    """Lists the diagram when diagrams are being found; True when it was (its render draws nothing)."""
    found = _DIAGRAMS_FOUND.get()
    if found is None:
        return False
    found.append(FoundDiagram(source=source, is_closed=is_closed))
    return True


def render_mermaid_meta(*, content_html: str, formatting_tags: FrozenSet[str]) -> str:
    raw_text = _extract_plain_text(content_html).strip("\n")
    if found_diagram(source=raw_text, is_closed=True):
        return ""
    copy_attr = _copyable_attr(formatting_tags, raw_text)
    return (
        f'<div class="meta-mermaid"{copy_attr}>'
        '<pre class="meta-mermaid-source">'
        f'<code class="language-mermaid">{html.escape(raw_text, quote=False)}</code>'
        "</pre>"
        "</div>"
    )


__all__ = ["render_mermaid_meta"]
