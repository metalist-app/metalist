// A search context's name in the list of search contexts: what its search box shows, the search;
// '(empty)' with none. A folder context (docs/ready-to-build/virtual-folders.md, "Folder contexts")
// is named by its folder, `/` for none, then what is typed in it ('Projects/ @todo'); a plain
// search never has a folder.
export const EMPTY_CONTEXT_LABEL = '(empty)';
export const NO_FOLDER_LABEL = '/';

export function searchContextLabel({ search, folder, isFolderContext }) {
    if (typeof search !== 'string' || typeof folder !== 'string' || typeof isFolderContext !== 'boolean') {
        throw new Error('searchContextLabel requires the search, the folder and whether it is a folder context');
    }
    if (isFolderContext) {
        const where = folder === '' ? NO_FOLDER_LABEL : folder;
        return [where, search].filter((part) => part !== '').join(' ');
    }
    if (folder !== '') {
        throw new Error('Only a folder context has a folder');
    }
    if (search === '') return EMPTY_CONTEXT_LABEL;
    return search;
}
