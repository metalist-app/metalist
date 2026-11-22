import assert from 'node:assert/strict';
import test from 'node:test';

import { chosenSectionReferenceText, sectionQueryOf } from '../../app/static/js/modules/mode-manager/services/reference-text.js';

// Links to a place in a note (the maintainer, 2026-11-21): what is typed after `[[` splits at
// its first `#`, and choosing a line writes `[[UUID#that line]]`.
const NOTE = 'c0000000-0000-4000-8000-000000000001';

test('what is typed splits at the first # into the note and the words of a line', () => {
    assert.equal(sectionQueryOf('Trip plan'), null);
    assert.deepEqual(sectionQueryOf('Trip plan#'), { noteQuery: 'Trip plan', lineQuery: '' });
    assert.deepEqual(sectionQueryOf('Trip plan#Day 3'), { noteQuery: 'Trip plan', lineQuery: 'Day 3' });
    assert.deepEqual(sectionQueryOf(`${NOTE}#issue #4`), { noteQuery: NOTE, lineQuery: 'issue #4' });
});

test('choosing a line writes the link and closes it, unless it is closed already', () => {
    assert.equal(chosenSectionReferenceText(NOTE, 'Day 3: Porto', ''), `[[${NOTE}#Day 3: Porto]]`);
    assert.equal(chosenSectionReferenceText(NOTE, 'Day 3: Porto', ' and more'), `[[${NOTE}#Day 3: Porto]]`);
    assert.equal(chosenSectionReferenceText(NOTE, 'Day 3: Porto', ']] and more'), `[[${NOTE}#Day 3: Porto`);
    assert.equal(chosenSectionReferenceText(NOTE, 'Day 3: Porto', '|the Porto day]]'), `[[${NOTE}#Day 3: Porto`);
});

test('a line a link cannot hold is refused', () => {
    for (const line of ['', '  ', 'a | b', 'see [[x]]', 'two\nlines']) {
        assert.throws(() => chosenSectionReferenceText(NOTE, line, ''), /a line a link can hold/, line);
    }
});
