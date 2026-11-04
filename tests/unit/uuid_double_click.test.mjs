import assert from 'node:assert/strict';
import test from 'node:test';

import { uuidRangeAt } from '../../app/static/js/modules/mode-manager/services/uuid-double-click-service.js';

// Double-clicking a UUID in a note being edited selects all of it (agreed 2026-10-31).
const UUID = 'b7414220-f998-45bc-b9f1-9d3a856e43c7';

test('any part of a UUID gives the whole UUID', () => {
    const text = `see ${UUID} here`;
    const start = text.indexOf(UUID);
    for (const part of UUID.split('-')) {
        const index = text.indexOf(part) + 1;
        assert.deepEqual(uuidRangeAt(text, index), { start, end: start + UUID.length }, part);
    }
});

test('inside a reference, the UUID alone', () => {
    for (const text of [`[[${UUID}]]`, `![[${UUID}]]`, `[[${UUID}|link text]]`]) {
        const range = uuidRangeAt(text, text.indexOf('45bc'));
        assert.equal(text.slice(range.start, range.end), UUID, text);
        assert.equal(uuidRangeAt(text, text.length - 1), null, text);
    }
});

test('other words and near-UUIDs are left to the browser', () => {
    assert.equal(uuidRangeAt('a well-known hyphen-word', 4), null);
    assert.equal(uuidRangeAt(`x${UUID}`, 5), null);
    assert.equal(uuidRangeAt(`${UUID}0`, 5), null);
    assert.equal(uuidRangeAt('b7414220-f998-45bc-b9f1-9d3a856e43c', 5), null);
});
