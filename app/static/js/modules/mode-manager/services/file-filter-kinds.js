// The Files filter's kinds (app/services/file_kinds.py), without the browser state the
// Files filter service keeps, so the menus can name them anywhere.

export const FILE_FILTER_KINDS = Object.freeze({
    NONE: 'none',
    ANY: 'any',
    IMAGE: 'image',
    PDF: 'pdf',
    MARKDOWN: 'markdown',
    // Notes with Links (app/services/link_filters.py): kinds of the same filter.
    LINKED: 'linked',
    LINKS: 'links',
    BROKEN_LINKS: 'broken-links',
});
export const FILE_KIND_NO_EXTENSION = 'no-extension';
// Any other file's kind is its extension (file_kinds.py).
const EXTENSION_KIND = /^\.[a-z0-9_+-]{1,12}$/;
// The kinds listed without asking the server, in order, with their labels.
export const FILE_FILTER_CHOICES = Object.freeze([
    [FILE_FILTER_KINDS.ANY, 'Any File'],
    [FILE_FILTER_KINDS.IMAGE, 'Images'],
    [FILE_FILTER_KINDS.PDF, 'PDFs'],
    [FILE_FILTER_KINDS.MARKDOWN, 'Markdown Files'],
]);
export const STANDARD_FILE_KINDS = Object.freeze([FILE_FILTER_KINDS.IMAGE, FILE_FILTER_KINDS.PDF, FILE_FILTER_KINDS.MARKDOWN]);
// Notes with Links (the maintainer, 2026-11-21, who set this order): the notes that link to a
// note, the notes other notes link to, and the notes with a link that leads nowhere.
export const LINK_FILTER_CHOICES = Object.freeze([
    [FILE_FILTER_KINDS.LINKS, 'Containing Links'],
    [FILE_FILTER_KINDS.LINKED, 'Linked from Other Notes'],
    [FILE_FILTER_KINDS.BROKEN_LINKS, 'With Broken Links'],
]);
const LINK_KINDS = new Set(LINK_FILTER_CHOICES.map(([kind]) => kind));
const NAMED_LABELS = new Map([[FILE_KIND_NO_EXTENSION, 'No Extension'], ...FILE_FILTER_CHOICES, ...LINK_FILTER_CHOICES]);

/** Whether the filter is about links, not about a kind of file (no File Size order then). */
export function isLinkFilterKind(kind) {
    return LINK_KINDS.has(kind);
}

export function isFileFilterKind(kind) {
    return typeof kind === 'string'
        && (kind === FILE_FILTER_KINDS.NONE || NAMED_LABELS.has(kind) || EXTENSION_KIND.test(kind));
}

// ".zip" as a word: ZIP.
export function extensionName(kind) {
    if (!EXTENSION_KIND.test(kind)) {
        throw new Error(`Not an extension kind: ${kind}`);
    }
    return kind.slice(1).toUpperCase();
}

/** A kind's name in the menus: "Images", "ZIP Files". */
export function fileFilterMenuLabel(kind) {
    if (NAMED_LABELS.has(kind)) {
        return NAMED_LABELS.get(kind);
    }
    return `${extensionName(kind)} Files`;
}
