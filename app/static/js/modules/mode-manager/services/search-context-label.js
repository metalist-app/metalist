// A search context's name in the list of search contexts: what its search box shows, the
// search, then the folder it is narrowed to (the chip after the search); '(empty)' with neither.
export const EMPTY_CONTEXT_LABEL = '(empty)';

export function searchContextLabel({ search, folder }) {
    if (typeof search !== 'string' || typeof folder !== 'string') {
        throw new Error('searchContextLabel requires the search and the folder');
    }
    const parts = [search, folder].filter((part) => part !== '');
    if (parts.length === 0) return EMPTY_CONTEXT_LABEL;
    return parts.join(' ');
}
