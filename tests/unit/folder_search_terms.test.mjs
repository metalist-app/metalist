import assert from 'node:assert/strict';
import test from 'node:test';

import { CHOSEN_FOLDER, CHOSEN_NONE, CHOSEN_TOP, chosenFolderOfSearch } from '../../app/static/js/modules/mode-manager/services/folder-search-terms.js';

test('the tree reads its chosen folder from the search, as the server does', () => {
    const cases = [
        ['', CHOSEN_TOP, ''],
        ['@todo', CHOSEN_TOP, ''],
        ['Projects/', CHOSEN_FOLDER, 'Projects/'],
        ['Projects/ @todo', CHOSEN_FOLDER, 'Projects/'],
        ['@todo +projects/client-a/', CHOSEN_FOLDER, 'projects/client-a/'],
        ['-Projects/', CHOSEN_TOP, ''],
        ['Projects/ Archive/', CHOSEN_NONE, ''],
        ['Projects/ OR Archive/', CHOSEN_NONE, ''],
        ['work OR home', CHOSEN_TOP, ''],
        ['"Projects/"', CHOSEN_TOP, ''],
    ];
    for (const [search, kind, folder] of cases) {
        assert.deepEqual(chosenFolderOfSearch(search), { kind, folder }, search);
    }
});
