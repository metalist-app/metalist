import assert from 'node:assert/strict';
import test from 'node:test';

import { shareWhileRunning } from '../../app/static/js/modules/share-while-running.js';

// The password-audit reminder asked for the vault's password count again while the first count
// was still running (the maintainer's problem report, 2026-11-22: two counts, 12 and 8 seconds,
// side by side). Checks made while a count runs now wait for that one.
function countingLoad() {
    const pending = [];
    const load = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
    return { pending, load };
}

test('callers while a request runs share it', async () => {
    const { pending, load } = countingLoad();
    const shared = shareWhileRunning(load);
    const first = shared();
    const second = shared();
    assert.equal(pending.length, 1, 'one request was made');
    pending[0].resolve(4);
    assert.deepEqual(await Promise.all([first, second]), [4, 4]);
});

test('a call after the request finished makes a new one', async () => {
    const { pending, load } = countingLoad();
    const shared = shareWhileRunning(load);
    const first = shared();
    pending[0].resolve(4);
    await first;
    const later = shared();
    assert.equal(pending.length, 2);
    pending[1].resolve(5);
    assert.equal(await later, 5);
});

test('a failed request fails its callers and the next call tries again', async () => {
    const { pending, load } = countingLoad();
    const shared = shareWhileRunning(load);
    const first = shared();
    const second = shared();
    pending[0].reject(new Error('offline'));
    await assert.rejects(first, /offline/);
    await assert.rejects(second, /offline/);
    const retry = shared();
    assert.equal(pending.length, 2);
    pending[1].resolve(1);
    assert.equal(await retry, 1);
});
