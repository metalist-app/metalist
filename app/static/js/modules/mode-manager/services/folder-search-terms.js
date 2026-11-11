// The folders a search chooses, as the tree marks them (docs/ready-to-build/folders-tab-and-multiple-folders.md
// §5; the server's virtual_folders.chosen_folders_of): every positive folder term (a term ending in /),
// in every OR clause, once each by case, A to Z; none for the top (`/`). Quoted text is text.

export const CHOSEN_FOLDERS = 'folders';
export const CHOSEN_TOP = 'top';
export const CHOSEN_NONE = 'none';

const FOLDER_MARK = '/';
const OR_KEYWORD = 'OR';
const EXCLUDE = '-';
const REQUIRE = '+';
// A term, or quoted text (kept whole, even unclosed).
const PIECE_RE = /"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?|[^\s"']+/g;

/** { kind, folders }: folders are the terms as typed for CHOSEN_FOLDERS, none otherwise. */
export function chosenFoldersOfSearch(search) {
    if (typeof search !== 'string') {
        throw new Error('chosenFoldersOfSearch requires the search');
    }
    const terms = Array.from(search.matchAll(PIECE_RE), (match) => match[0]);
    const isQuoted = (term) => term.startsWith('"') || term.startsWith("'");
    const folders = new Map();
    for (const term of terms) {
        if (isQuoted(term) || term === OR_KEYWORD || term.startsWith(EXCLUDE)) continue;
        const folder = term.startsWith(REQUIRE) ? term.slice(REQUIRE.length) : term;
        if (folder.length <= FOLDER_MARK.length || !folder.endsWith(FOLDER_MARK)) continue;
        if (!folders.has(folder.toLowerCase())) folders.set(folder.toLowerCase(), folder);
    }
    if (folders.size === 0) return { kind: CHOSEN_TOP, folders: [] };
    // A to Z, as the server sends them.
    const keys = [...folders.keys()].sort();
    return { kind: CHOSEN_FOLDERS, folders: keys.map((key) => folders.get(key)) };
}
