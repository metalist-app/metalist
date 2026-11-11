// The Files filter's kinds (app/services/file_kinds.py), without the browser state the
// Files filter service keeps, so the menus can name them anywhere.

export const FILE_FILTER_KINDS = Object.freeze({
    NONE: 'none',
    ANY: 'any',
    IMAGE: 'image',
    PDF: 'pdf',
    MARKDOWN: 'markdown',
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
const NAMED_LABELS = new Map([[FILE_KIND_NO_EXTENSION, 'No Extension'], ...FILE_FILTER_CHOICES]);

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
