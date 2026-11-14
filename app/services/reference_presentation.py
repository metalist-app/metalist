"""View-only reference chrome; no saved content or persistent caches."""

import html

from app.services.embedded_references import EmbedRenderContext, shows_note_embed

def referrer_badge_title(referrer_count: int) -> str:
    assert isinstance(referrer_count, int) and referrer_count > 0, referrer_count
    # Backlinks, the word the page it opens uses (the maintainer, 2026-11-13).
    if referrer_count == 1:
        return "1 backlink"
    return f"{referrer_count:,} backlinks"


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
        classes.append("note-with-backlinks")
        title = html.escape(referrer_badge_title(referrer_count), quote=True)
        # The backlinks icon, drawn by main.css (the link icon mirrored: the maintainer,
        # 2026-11-13); the count is in the tooltip. No text, so find and search
        # marks never read it as the note's words.
        badge = (
            '<button type="button" class="note-backlinks-link note-backlinks-badge" '
            f'data-source-note-id="{html.escape(note_id, quote=True)}" '
            f'title="{title}" aria-label="{title}"></button>'
        )
    if not classes:
        return rendered_content
    return f'<div class="{" ".join(classes)}">{badge}{rendered_content}</div>'
