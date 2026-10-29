"""View-only reference chrome; no saved content or persistent caches."""

import html

from app.services.embedded_references import EmbedRenderContext, shows_note_embed

# The Referenced by badge shows counts up to this; more read "99+" (docs/ui/references.md).
MAX_SHOWN_REFERRER_COUNT = 99
# Counts of this many digits or more make the circle a pill, and the first line makes more room.
_WIDE_BADGE_DIGITS = 2


def referrer_badge_text(referrer_count: int) -> str:
    """The badge's number: the count, or "99+" past the largest one shown."""
    assert isinstance(referrer_count, int) and referrer_count > 0, referrer_count
    if referrer_count > MAX_SHOWN_REFERRER_COUNT:
        return f"{MAX_SHOWN_REFERRER_COUNT}+"
    return str(referrer_count)


def referrer_badge_title(referrer_count: int) -> str:
    assert isinstance(referrer_count, int) and referrer_count > 0, referrer_count
    if referrer_count == 1:
        return "Referenced by 1 note"
    return f"Referenced by {referrer_count:,} notes"


def _badge_width_class(badge_text: str) -> str:
    if badge_text.endswith("+"):
        return "note-with-backlinks-widest"
    if len(badge_text) >= _WIDE_BADGE_DIGITS:
        return "note-with-backlinks-wide"
    return ""


def decorate_note_references(
    *, note_id: str, content_html: str, tags: str, rendered_content: str,
    context: EmbedRenderContext, referrer_count: int,
) -> str:
    assert context.has_note(note_id)
    assert isinstance(referrer_count, int) and referrer_count >= 0, referrer_count
    classes = []
    if shows_note_embed(content_html=content_html, context=context):
        classes.append("note-reference-only")
    badge = ""
    if referrer_count > 0:
        badge_text = referrer_badge_text(referrer_count)
        classes.append("note-with-backlinks")
        width_class = _badge_width_class(badge_text)
        if width_class != "":
            classes.append(width_class)
        title = html.escape(referrer_badge_title(referrer_count), quote=True)
        # The number is drawn from data-referrer-count (main.css), not written as text, so
        # find and search marks never read it as the note's words.
        badge = (
            '<button type="button" class="note-backlinks-link note-backlinks-badge" '
            f'data-source-note-id="{html.escape(note_id, quote=True)}" data-referrer-count="{badge_text}" '
            f'title="{title}" aria-label="{title}"></button>'
        )
    if not classes:
        return rendered_content
    return f'<div class="{" ".join(classes)}">{badge}{rendered_content}</div>'
