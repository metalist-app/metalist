import assert from 'node:assert/strict';
import test from 'node:test';

import { MAX_CONCURRENT_TRANSFERS, inTransferSlot } from '../../app/static/js/modules/file-transfer-slots.js';

const OK = 200;
const PICTURES = 6;

// A folder's transfers go a few at a time, the rest waiting for a slot.
test('at most four downloads run at once, and every one finishes', async () => {
    let running = 0;
    let most = 0;
    let finished = 0;
    const releases = [];
    const downloads = Array.from({ length: PICTURES }, () => inTransferSlot(async () => {
        running += 1;
        most = Math.max(most, running);
        await new Promise((resolve) => releases.push(resolve));
        running -= 1;
        finished += 1;
        return { response: { status: OK } };
    }));
    // Let each download that got a slot start, then finish one at a time.
    while (finished < PICTURES) {
        await new Promise((resolve) => setImmediate(resolve));
        const release = releases.shift();
        if (release !== undefined) release();
    }
    const results = await Promise.all(downloads);
    assert.equal(most, MAX_CONCURRENT_TRANSFERS);
    assert.equal(results.length, PICTURES);
    assert.ok(results.every((result) => result.response.status === OK));
});
