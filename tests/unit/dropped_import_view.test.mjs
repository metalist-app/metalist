import assert from 'node:assert/strict';
import test from 'node:test';

import { DROPPED_IMPORT_VIEWS, droppedImportView } from '../../app/static/js/modules/wizard/dropped-import-view.js';

// A dropped folder or bookmarks file ends on what it brought in: the maintainer, 2026-11-09.
const { IN_ITS_CONTEXT, ITS_NEW_FOLDER, ITS_OWN_SEARCH } = DROPPED_IMPORT_VIEWS;

for (const [name, situation, view] of [
    ['a new folder, the tree showing', { isDroppedFiles: false, isNewFolder: true, isInFolderContext: true }, ITS_NEW_FOLDER],
    ['no folder, the tree showing', { isDroppedFiles: false, isNewFolder: false, isInFolderContext: true }, ITS_OWN_SEARCH],
    ['a new folder in a plain search', { isDroppedFiles: false, isNewFolder: true, isInFolderContext: false }, ITS_OWN_SEARCH],
    ['no new folder in a plain search', { isDroppedFiles: false, isNewFolder: false, isInFolderContext: false }, ITS_OWN_SEARCH],
    ['loose files, the tree showing', { isDroppedFiles: true, isNewFolder: true, isInFolderContext: true }, IN_ITS_CONTEXT],
    ['loose files in a plain search', { isDroppedFiles: true, isNewFolder: false, isInFolderContext: false }, IN_ITS_CONTEXT],
]) {
    test(`a drop's import ends on the right view: ${name}`, () => {
        assert.equal(droppedImportView(situation), view);
    });
}
