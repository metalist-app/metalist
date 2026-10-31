import assert from 'node:assert/strict';
import test from 'node:test';

import { chosenReferenceText } from '../../app/static/js/modules/mode-manager/services/reference-text.js';

// Choosing a note in the `[[` list (docs/ui/references.md, Suggestions).
const NOTE_ID = 'b1addd3a-3ae2-43fc-9286-025ca44b359b';

test('a note chosen after a bare [[ gets its closing brackets', () => {
    assert.equal(chosenReferenceText(NOTE_ID, ''), `[[${NOTE_ID}]]`);
    assert.equal(chosenReferenceText(NOTE_ID, ' more text'), `[[${NOTE_ID}]]`);
    assert.equal(chosenReferenceText(NOTE_ID, ' and [[other]]'), `[[${NOTE_ID}]]`);
});

test('a note chosen inside [[ ]] keeps the closing brackets already there, and its link text', () => {
    // Typing between [[ and ]] (bug 2026-10-31: the choice gave [[id]]]]).
    assert.equal(chosenReferenceText(NOTE_ID, ']]'), `[[${NOTE_ID}`);
    assert.equal(chosenReferenceText(NOTE_ID, ']] after'), `[[${NOTE_ID}`);
    assert.equal(chosenReferenceText(NOTE_ID, '|its own text]]'), `[[${NOTE_ID}`);
});
