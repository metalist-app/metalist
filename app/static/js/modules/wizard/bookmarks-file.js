import { NotesAPI } from '../api-client.js';

// A browser's bookmarks export (docs/ready-to-build/bookmark-import.md): recognized by its
// first line, never by its name (bookmark_import.py's BOOKMARKS_DOCTYPE), and read into the
// import walkthrough's choices, whether chosen on its File screen or dropped on MetaList.

const BOOKMARKS_DOCTYPE = '<!doctype netscape-bookmark-file-1>';
// What may come before it: a byte order mark and blank space.
const LEADING_RE = /^[﻿\s]*/;
// Enough of the start of a file to read its first line.
const HEAD_BYTES = 256;
// Only a web page's name can hold an export; every other dropped file is never read for it.
const WEB_PAGE_NAME_RE = /\.html?$/i;
// The folder the bookmarks go into, at first (§4).
export const BOOKMARKS_FOLDER = 'Bookmarks';

export function isBookmarksExportText(text) {
    if (typeof text !== 'string') {
        throw new Error('isBookmarksExportText requires text');
    }
    return text.replace(LEADING_RE, '').slice(0, BOOKMARKS_DOCTYPE.length).toLowerCase() === BOOKMARKS_DOCTYPE;
}

/** Whether a file's name is a web page's, the only name an export has (read before reading it). */
export function hasWebPageName(file) {
    if (!(file instanceof File)) {
        throw new Error('hasWebPageName requires a File');
    }
    return WEB_PAGE_NAME_RE.test(file.name);
}

/** Whether a dropped file is a bookmarks export: a web page's name, and the export's first line. */
export async function isBookmarksExportFile(file) {
    if (!hasWebPageName(file)) return false;
    return isBookmarksExportText(await file.slice(0, HEAD_BYTES).text());
}

/**
 * The walkthrough's choices for a bookmarks file: its text, name and counts (the server's
 * preview), or the sentence saying it isn't an export. The bookmarks go into
 * BOOKMARKS_FOLDER at first.
 */
export async function bookmarksFileChoices(file) {
    if (!(file instanceof File)) {
        throw new Error('bookmarksFileChoices requires a File');
    }
    const text = await file.text();
    const chosen = {
        source: 'bookmarks', bookmarksFileName: file.name, prefixText: BOOKMARKS_FOLDER,
        bookmarksText: '', bookmarkCount: 0, bookmarkFolderCount: 0, bookmarksProblem: '',
    };
    if (!isBookmarksExportText(text)) {
        return { ...chosen, bookmarksProblem: 'That file isn\'t a bookmarks export. Export your bookmarks from the browser and choose that file.' };
    }
    const preview = await NotesAPI.previewBookmarkImport({ fileText: text, prefixFolder: BOOKMARKS_FOLDER });
    if (!Number.isInteger(preview.bookmarkCount) || !Number.isInteger(preview.folderCount)) {
        throw new Error('Bookmarks preview answered malformed');
    }
    return { ...chosen, bookmarksText: text, bookmarkCount: preview.bookmarkCount, bookmarkFolderCount: preview.folderCount };
}
