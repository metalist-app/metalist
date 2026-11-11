// The text of a reference to a note (docs/ui/references.md): `[[UUID]]`, with optional
// `|link text` before its closing brackets.

export const REFERENCE_OPEN = '[[';
const REFERENCE_CLOSE = ']]';
// The rest of a reference already written after the caret: its closing brackets, after
// any `|link text` (typing between `[[` and `]]`).
const REFERENCE_REST_RE = /^(?:\|[^[\]\n]*)?\]\]/;

/** What choosing a note in the `[[` list writes in place of `[[` and the text typed after it. */
export function chosenReferenceText(noteId, textAfterCaret) {
    if (typeof noteId !== 'string' || noteId === '' || typeof textAfterCaret !== 'string') {
        throw new Error('chosenReferenceText requires a note id and the text after the caret');
    }
    if (REFERENCE_REST_RE.test(textAfterCaret)) {
        // The closing brackets are there already (bug 2026-10-31: they were doubled).
        return `${REFERENCE_OPEN}${noteId}`;
    }
    return `${REFERENCE_OPEN}${noteId}${REFERENCE_CLOSE}`;
}

const SEARCH_LINK_PREFIX = 'search:';

/** What choosing a search in the `[[` list writes: its search link (docs/ready-to-build/search-links.md). */
export function chosenSearchLinkText(search, textAfterCaret) {
    if (typeof search !== 'string' || search.trim() === '' || typeof textAfterCaret !== 'string') {
        throw new Error('chosenSearchLinkText requires a search and the text after the caret');
    }
    if (REFERENCE_REST_RE.test(textAfterCaret)) {
        return `${REFERENCE_OPEN}${SEARCH_LINK_PREFIX}${search}`;
    }
    return `${REFERENCE_OPEN}${SEARCH_LINK_PREFIX}${search}${REFERENCE_CLOSE}`;
}

