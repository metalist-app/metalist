import assert from 'node:assert/strict';
import test from 'node:test';

import { notesMayHaveChanged, onNotesChanged } from '../../app/static/js/modules/notes-change-signal.js';

// Whoever listens is told each time the notes may have changed, until it stops listening.
test('listeners are told of changes until they stop listening', () => {
    let told = 0;
    const stop = onNotesChanged(() => { told += 1; });
    notesMayHaveChanged();
    notesMayHaveChanged();
    assert.equal(told, 2);
    stop();
    notesMayHaveChanged();
    assert.equal(told, 2);
});

test('a listener must be a function', () => {
    assert.throws(() => onNotesChanged(null), /requires a listener/);
});
