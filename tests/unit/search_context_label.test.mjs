import assert from 'node:assert/strict';
import test from 'node:test';

import { EMPTY_CONTEXT_LABEL, NO_FOLDER_LABEL, searchContextLabel } from '../../app/static/js/modules/mode-manager/services/search-context-label.js';

// A search context narrowed to a folder with no search typed showed "(empty)" in the list of
// search contexts (2026-11-07). Since the same day only folder contexts have a folder
// (docs/ready-to-build/virtual-folders.md, "Folder contexts"): each is named by its folder, then its search.

test('the folder context, with no search, is named by its folder', () => {
    assert.equal(searchContextLabel({ search: '', folder: 'OLD_PICS/', isFolderContext: true }), 'OLD_PICS/');
});

test('the folder context with a search: the folder, then the search', () => {
    assert.equal(searchContextLabel({ search: '@todo', folder: 'Projects/', isFolderContext: true }), 'Projects/ @todo');
});

test('the folder context with no folder reads /', () => {
    assert.equal(searchContextLabel({ search: '', folder: '', isFolderContext: true }), NO_FOLDER_LABEL);
    assert.equal(searchContextLabel({ search: '@todo', folder: '', isFolderContext: true }), '/ @todo');
    assert.equal(NO_FOLDER_LABEL, '/');
});

test('a search alone is its search', () => {
    assert.equal(searchContextLabel({ search: 'ML3-business', folder: '', isFolderContext: false }), 'ML3-business');
});

test('neither is empty', () => {
    assert.equal(searchContextLabel({ search: '', folder: '', isFolderContext: false }), EMPTY_CONTEXT_LABEL);
    assert.equal(EMPTY_CONTEXT_LABEL, '(empty)');
});

test('no other context has a folder', () => {
    assert.throws(() => searchContextLabel({ search: '', folder: 'Projects/', isFolderContext: false }), /Only a folder context/);
});
