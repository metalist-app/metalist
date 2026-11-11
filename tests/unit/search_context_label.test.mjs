import assert from 'node:assert/strict';
import test from 'node:test';

import { EMPTY_CONTEXT_LABEL, NO_FOLDER_LABEL, searchContextLabel } from '../../app/static/js/modules/mode-manager/services/search-context-label.js';

// A search context is named by its search, a folder chosen in the tree included, since the folder
// became search text (2026-11-11, docs/ready-to-build/folder-tags-in-search.md §2).

test('a folder context is named by its search, its folder first when chosen', () => {
    assert.equal(searchContextLabel({ search: 'OLD_PICS/', isFolderContext: true }), 'OLD_PICS/');
    assert.equal(searchContextLabel({ search: 'Projects/ @todo', isFolderContext: true }), 'Projects/ @todo');
});

test('a folder context with an empty search reads /', () => {
    assert.equal(searchContextLabel({ search: '', isFolderContext: true }), NO_FOLDER_LABEL);
    assert.equal(NO_FOLDER_LABEL, '/');
});

test('a search alone is its search', () => {
    assert.equal(searchContextLabel({ search: 'ML3-business', isFolderContext: false }), 'ML3-business');
});

test('a plain search with none is empty', () => {
    assert.equal(searchContextLabel({ search: '', isFolderContext: false }), EMPTY_CONTEXT_LABEL);
    assert.equal(EMPTY_CONTEXT_LABEL, '(empty)');
});
