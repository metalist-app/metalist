import assert from 'node:assert/strict';
import test from 'node:test';

import { EMPTY_CONTEXT_LABEL, searchContextLabel } from '../../app/static/js/modules/mode-manager/services/search-context-label.js';

// A search context narrowed to a folder with no search typed showed "(empty)" in the list of
// search contexts (2026-11-07): it shows what its search box shows, the search, then the folder.

test('a context narrowed to a folder, with no search, is named by its folder', () => {
    assert.equal(searchContextLabel({ search: '', folder: 'OLD_PICS/' }), 'OLD_PICS/');
});

test('a search and a folder show as in the search box: the search, then the folder', () => {
    assert.equal(searchContextLabel({ search: 'journal', folder: 'OLD_PICS/' }), 'journal OLD_PICS/');
});

test('a search alone is its search', () => {
    assert.equal(searchContextLabel({ search: 'ML3-business', folder: '' }), 'ML3-business');
});

test('neither is empty', () => {
    assert.equal(searchContextLabel({ search: '', folder: '' }), EMPTY_CONTEXT_LABEL);
    assert.equal(EMPTY_CONTEXT_LABEL, '(empty)');
});
