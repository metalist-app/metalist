// The shared most-recent-first cache helpers of the picture caches (unbounded-growth-audit.md, M8).
import assert from 'node:assert/strict';
import test from 'node:test';

import {
    RECENT_PICTURES_CAPACITY,
    RECENT_SIZES_CAPACITY,
    evictOldest,
    rememberSize,
    useNewest,
} from '../../app/static/js/modules/object-url-cache.js';

test('both caps are 200 entries', () => {
    assert.equal(RECENT_PICTURES_CAPACITY, 200);
    assert.equal(RECENT_SIZES_CAPACITY, 200);
});

test('remembered sizes keep the 200 most recently remembered', () => {
    const sizes = new Map();
    for (let number = 1; number <= 250; number += 1) rememberSize(sizes, `diagram-${number}`, number);
    assert.equal(sizes.size, 200);
    assert.equal(sizes.has('diagram-50'), false);
    assert.equal(sizes.get('diagram-51'), 51);
    // Remembering an old one again makes it the newest: the next one drops diagram-52 instead.
    rememberSize(sizes, 'diagram-51', 510);
    rememberSize(sizes, 'diagram-251', 251);
    assert.equal(sizes.get('diagram-51'), 510);
    assert.equal(sizes.has('diagram-52'), false);
    assert.equal(sizes.size, 200);
});

test('a used entry becomes the newest, and eviction skips what may not go yet', () => {
    const cache = new Map([['a', 1], ['b', 2], ['c', 3], ['d', 4]]);
    assert.equal(useNewest(cache, 'a'), 1);
    assert.deepEqual([...cache.keys()], ['b', 'c', 'd', 'a']);
    assert.deepEqual(evictOldest(cache, 2, (key) => key !== 'b'), [['c', 3], ['d', 4]]);
    assert.deepEqual([...cache.keys()], ['b', 'a']);
    assert.throws(() => useNewest(cache, 'c'), /No cache entry/);
});
