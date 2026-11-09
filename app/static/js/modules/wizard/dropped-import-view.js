// Where a dropped import ends (the maintainer, 2026-11-09: "if I import some stuff, I want at the
// end of the process to see the stuff"): a dropped folder or bookmarks file on the folder it made
// when the tree shows one to choose, else on a search of just that import. Loose files dropped
// through the walkthrough stay in the search context they were dropped in.
export const DROPPED_IMPORT_VIEWS = Object.freeze({
    IN_ITS_CONTEXT: 'in-its-context',
    ITS_NEW_FOLDER: 'its-new-folder',
    ITS_OWN_SEARCH: 'its-own-search',
});

export function droppedImportView({ isDroppedFiles, isNewFolder, isInFolderContext }) {
    if (typeof isDroppedFiles !== 'boolean' || typeof isNewFolder !== 'boolean' || typeof isInFolderContext !== 'boolean') {
        throw new Error('droppedImportView requires what was dropped and where');
    }
    if (isDroppedFiles) return DROPPED_IMPORT_VIEWS.IN_ITS_CONTEXT;
    if (isNewFolder && isInFolderContext) return DROPPED_IMPORT_VIEWS.ITS_NEW_FOLDER;
    return DROPPED_IMPORT_VIEWS.ITS_OWN_SEARCH;
}
