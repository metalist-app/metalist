// The folder a search chooses, as the tree marks it (docs/ready-to-build/folder-tags-in-search.md §3;
// the server's virtual_folders.chosen_folder_of): its one positive folder term (a term ending in /),
// none for the top (`/`), nothing marked for two, or for folders joined by OR. Quoted text is text.

export const CHOSEN_FOLDER = 'folder';
export const CHOSEN_TOP = 'top';
export const CHOSEN_NONE = 'none';

const FOLDER_MARK = '/';
const OR_KEYWORD = 'OR';
const EXCLUDE = '-';
const REQUIRE = '+';
// A term, or quoted text (kept whole, even unclosed).
const PIECE_RE = /"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?|[^\s"']+/g;

/** { kind, folder }: folder is the term as typed for CHOSEN_FOLDER, '' otherwise. */
export function chosenFolderOfSearch(search) {
    if (typeof search !== 'string') {
        throw new Error('chosenFolderOfSearch requires the search');
    }
    const terms = Array.from(search.matchAll(PIECE_RE), (match) => match[0]);
    const isQuoted = (term) => term.startsWith('"') || term.startsWith("'");
    const hasOr = terms.includes(OR_KEYWORD);
    const folders = terms
        .filter((term) => !isQuoted(term) && !term.startsWith(EXCLUDE))
        .map((term) => (term.startsWith(REQUIRE) ? term.slice(REQUIRE.length) : term))
        .filter((term) => term.length > FOLDER_MARK.length && term.endsWith(FOLDER_MARK));
    if (folders.length === 0) return { kind: CHOSEN_TOP, folder: '' };
    if (hasOr || folders.length > 1) return { kind: CHOSEN_NONE, folder: '' };
    return { kind: CHOSEN_FOLDER, folder: folders[0] };
}
