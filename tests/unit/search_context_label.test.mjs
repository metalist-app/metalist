import assert from 'node:assert/strict';
import test from 'node:test';

import { EMPTY_CONTEXT_LABEL, searchContextLabel } from '../../app/static/js/modules/mode-manager/services/search-context-label.js';

// A search context is named by its search, a folder chosen in the tree included, since the folder
// became search text (2026-11-11, docs/ready-to-build/folder-tags-in-search.md §2); folder contexts
// became ordinary ones (folders-tab-and-multiple-folders.md §1).

test('a search context is named by its search, its folders included', () => {
    assert.equal(searchContextLabel({ search: 'OLD_PICS/' }), 'OLD_PICS/');
    assert.equal(searchContextLabel({ search: 'Projects/ Archive/ @todo' }), 'Projects/ Archive/ @todo');
    assert.equal(searchContextLabel({ search: 'ML3-business' }), 'ML3-business');
});

test('a search context with no search is empty', () => {
    assert.equal(searchContextLabel({ search: '' }), EMPTY_CONTEXT_LABEL);
    assert.equal(EMPTY_CONTEXT_LABEL, '(empty)');
});
