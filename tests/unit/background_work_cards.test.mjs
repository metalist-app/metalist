import assert from 'node:assert/strict';
import test from 'node:test';

import { workProgressParts, workProgressText } from '../../app/static/js/modules/mode-manager/services/background-work-text.js';

// Background work says how far it got, how long it has run, and about how long is left (the
// maintainer, 2026-11-02).
test('work says how far it got, its time so far and the time left at that pace', () => {
    const entry = { key: 'file-texts', label: 'Reading PDF text', done: 3, total: 7, elapsedSeconds: 12 };
    assert.equal(workProgressText(entry), 'Reading PDF text: 3 of 7 · 0:12 so far, about 0:16 left');
});

test('before any part is done, or while the total is unknown, there is no estimate', () => {
    assert.equal(workProgressText({ key: 'import', label: 'Importing files', done: 0, total: 40, elapsedSeconds: 2 }),
        'Importing files: 0 of 40 · 0:02 so far');
    assert.equal(workProgressText({ key: 'import', label: 'Importing files', done: 0, total: 0, elapsedSeconds: 65 }),
        'Importing files… · 1:05 so far');
});

// The card (2026-11-03): the line, then above the bar the time spent at the left and the time
// left at the right, without words around them.
test('a card shows the line, the time spent and the time left, apart', () => {
    assert.deepEqual(workProgressParts({ key: 'file-texts', label: 'Reading document text', done: 79, total: 1490, elapsedSeconds: 87 }),
        { label: 'Reading document text: 79 of 1490', spent: '1:27', left: '25:54' });
});

test('a card has no time left before an estimate', () => {
    assert.deepEqual(workProgressParts({ key: 'import', label: 'Importing files', done: 0, total: 40, elapsedSeconds: 2 }),
        { label: 'Importing files: 0 of 40', spent: '0:02', left: '' });
    assert.deepEqual(workProgressParts({ key: 'import', label: 'Importing files', done: 0, total: 0, elapsedSeconds: 65 }),
        { label: 'Importing files…', spent: '1:05', left: '' });
});

test('long work reads in hours', () => {
    assert.equal(workProgressText({ key: 'file-texts', label: 'Reading PDF text', done: 100, total: 300, elapsedSeconds: 1900 }),
        'Reading PDF text: 100 of 300 · 31:40 so far, about 1:03:20 left');
});
