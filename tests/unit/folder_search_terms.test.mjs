import assert from 'node:assert/strict';
import test from 'node:test';

import { CHOSEN_FOLDERS, CHOSEN_TOP, chosenFoldersOfSearch } from '../../app/static/js/modules/mode-manager/services/folder-search-terms.js';

// Every positive folder term is marked, in every OR clause (folders-tab-and-multiple-folders.md §5).
test('the tree reads its chosen folders from the search, as the server does', () => {
    const cases = [
        ['', CHOSEN_TOP, []],
        ['@todo', CHOSEN_TOP, []],
        ['Projects/', CHOSEN_FOLDERS, ['Projects/']],
        ['Projects/ @todo', CHOSEN_FOLDERS, ['Projects/']],
        ['@todo +projects/client-a/', CHOSEN_FOLDERS, ['projects/client-a/']],
        ['-Projects/', CHOSEN_TOP, []],
        ['Projects/ Archive/', CHOSEN_FOLDERS, ['Archive/', 'Projects/']],
        ['Projects/ OR Archive/ @todo', CHOSEN_FOLDERS, ['Archive/', 'Projects/']],
        ['Projects/ projects/', CHOSEN_FOLDERS, ['Projects/']],
        ['work OR home', CHOSEN_TOP, []],
        ['"Projects/"', CHOSEN_TOP, []],
    ];
    for (const [search, kind, folders] of cases) {
        assert.deepEqual(chosenFoldersOfSearch(search), { kind, folders }, search);
    }
});
