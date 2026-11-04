"""The checkbox drawn for @todo and @done notes and for Markdown tasks (- [ ] and - [x]):
one look for every box (docs/ui/content-formatting.md)."""

from __future__ import annotations

_BOX = (
    '<rect x="3" y="3" width="18" height="18" rx="3" ry="3" '
    'fill="none" stroke="currentColor" stroke-width="2" />'
)
_TICK = (
    '<path d="M7 12l3 3 7-7" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />'
)
_SVG_OPEN = '<svg class="meta-status-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'

EMPTY_BOX_ICON = f"{_SVG_OPEN}{_BOX}</svg>"
TICKED_BOX_ICON = f"{_SVG_OPEN}{_BOX}{_TICK}</svg>"
