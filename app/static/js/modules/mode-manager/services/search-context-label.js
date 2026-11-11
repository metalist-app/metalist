// A search context's name in the list of search contexts: what its search box shows, the search.
// A folder context (docs/ready-to-build/virtual-folders.md, "Folder contexts") with none is `/`, every
// note; a plain search with none is '(empty)'. A folder chosen in the tree is in the search
// ('Projects/ @todo', docs/ready-to-build/folder-tags-in-search.md).
export const EMPTY_CONTEXT_LABEL = '(empty)';
export const NO_FOLDER_LABEL = '/';

export function searchContextLabel({ search, isFolderContext }) {
    if (typeof search !== 'string' || typeof isFolderContext !== 'boolean') {
        throw new Error('searchContextLabel requires the search and whether it is a folder context');
    }
    if (search !== '') return search;
    return isFolderContext ? NO_FOLDER_LABEL : EMPTY_CONTEXT_LABEL;
}
