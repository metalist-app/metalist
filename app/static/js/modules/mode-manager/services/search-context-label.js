// A search context's name in the list of search contexts: what its search box shows, the search,
// a folder chosen in the tree included ('Projects/ @todo', docs/ready-to-build/folder-tags-in-search.md);
// with none, '(empty)'. Folder contexts, which read `/` with none, became ordinary search contexts on
// 2026-11-11 (docs/ready-to-build/folders-tab-and-multiple-folders.md §1).
export const EMPTY_CONTEXT_LABEL = '(empty)';

export function searchContextLabel({ search }) {
    if (typeof search !== 'string') {
        throw new Error('searchContextLabel requires the search');
    }
    if (search !== '') return search;
    return EMPTY_CONTEXT_LABEL;
}
