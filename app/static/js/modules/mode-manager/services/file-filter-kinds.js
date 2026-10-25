// The Files filter's kinds (app/services/file_kinds.py), without the browser state the
// Files filter service keeps, so the menus can name them anywhere.

export const FILE_FILTER_KINDS = Object.freeze({
    NONE: 'none',
    ANY: 'any',
    IMAGE: 'image',
    PDF: 'pdf',
    MARKDOWN: 'markdown',
});
// The kinds the Notes with Files menus offer after All Notes, in order, with their labels.
export const FILE_FILTER_CHOICES = Object.freeze([
    [FILE_FILTER_KINDS.ANY, 'Any File'],
    [FILE_FILTER_KINDS.IMAGE, 'Images'],
    [FILE_FILTER_KINDS.PDF, 'PDFs'],
    [FILE_FILTER_KINDS.MARKDOWN, 'Markdown Files'],
]);
