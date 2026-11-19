import { normalizeTagBarInput } from './tag-syntax-service.js';
import { splitTokens } from '../../quoted-values.js';

// A Markdown file dropped into an empty note, made a note (the text-drop question's "Note"):
// the note is tagged @markdown, so its text shows as Markdown and not as its source (the
// maintainer, 2026-11-18). A note that already holds text keeps its tags: the dropped text
// joins what is there, whatever that is.

export const MARKDOWN_TAG = '@markdown';
const MARKDOWN_FILE_NAME = /\.(md|markdown)$/i;

// The tag bar's text after the drop: with @markdown added when it applies, else as it was.
export function tagsAfterTextDrop({ tags, fileNames, noteIsEmpty }) {
    if (typeof tags !== 'string' || !Array.isArray(fileNames) || typeof noteIsEmpty !== 'boolean') {
        throw new Error('tagsAfterTextDrop requires the tags, the dropped files\' names and whether the note is empty');
    }
    if (!noteIsEmpty || !fileNames.some((name) => MARKDOWN_FILE_NAME.test(name))) {
        return tags;
    }
    const normalized = normalizeTagBarInput(tags);
    if (splitTokens(normalized).some((tag) => tag.toLowerCase() === MARKDOWN_TAG)) {
        return tags;
    }
    return normalizeTagBarInput(`${normalized} ${MARKDOWN_TAG}`);
}
