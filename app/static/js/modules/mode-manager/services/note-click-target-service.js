const MARKDOWN_FOLD_SELECTOR = 'details.meta-markdown-callout-fold, details.meta-markdown-html-fold';

function supportsClosest(target) {
    return target !== null && typeof target === 'object' && typeof target.closest === 'function';
}

export function isViewModeNoteLink(target) {
    if (!supportsClosest(target)) {
        return false;
    }
    const anchor = target.closest('a[href]');
    if (!anchor || !anchor.closest('.note-content')) {
        return false;
    }
    const note = anchor.closest('.note');
    return note !== null && !note.classList.contains('editing');
}

export function isViewModeNoteDisclosureToggle(target) {
    if (!supportsClosest(target)) {
        return false;
    }
    if (viewModeCalloutTitleAt(target) !== null) {
        return true;
    }
    const summary = target.closest('summary.ai-chat-references-heading');
    if (!summary) {
        return false;
    }
    const disclosure = summary.closest('details.ai-chat-references-disclosure');
    if (!disclosure || !summary.closest('.note-content')) {
        return false;
    }
    const note = summary.closest('.note');
    return note !== null && !note.classList.contains('editing');
}

// The title of a folding Markdown callout, or of a <details> fold written in a Markdown
// note (docs/ui/content-formatting.md, Callouts and HTML), in a note being viewed, open (not
// collapsed to its first line): a click there folds it, as the browser's own disclosure
// does, without editing or dragging the note. Null elsewhere.
export function viewModeCalloutTitleAt(target) {
    if (!supportsClosest(target)) {
        return null;
    }
    const summary = target.closest('summary');
    if (!summary || !summary.parentElement || !summary.parentElement.matches(MARKDOWN_FOLD_SELECTOR)) {
        return null;
    }
    if (!summary.closest('.note-content')) {
        return null;
    }
    const note = summary.closest('.note');
    if (note === null || note.classList.contains('editing') || note.classList.contains('collapsed')) {
        return null;
    }
    return summary;
}

export function resolveNonContentNoteSelectionTarget(target) {
    if (!supportsClosest(target)) {
        return null;
    }

    if (target.closest('.note-content')) {
        return null;
    }

    if (target.closest('.note-tag-bar')) {
        return null;
    }

    if (target.closest('.note-collapse-toggle')) {
        return null;
    }

    if (target.closest('.note-collapsed-children-indicator')) {
        return null;
    }

    return target.closest('.note');
}
