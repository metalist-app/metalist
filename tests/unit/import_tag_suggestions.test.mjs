import { test } from 'node:test';
import assert from 'node:assert/strict';

import { withoutFolderTags } from '../../app/static/js/modules/import-folder-tags.js';

// The AI's tags for an import (PLAN.md, slice 2b) never include the import's folder tags:
// a note has its own folder's tag from its file, and on any other note it would be wrong.
test('folder tags are taken out of the proposals, in any case, and notes left with none drop out', () => {
    const proposals = {
        a: ['travel', 'Projects/Client-A', 'lisbon'],
        b: ['projects/client-a'],
        c: ['Daily/2026', 'journal'],
    };
    assert.deepEqual(withoutFolderTags(proposals, ['Projects/Client-A', 'Daily/2026']), {
        a: ['travel', 'lisbon'],
        c: ['journal'],
    });
});
