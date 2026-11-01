import { test } from 'node:test';
import assert from 'node:assert/strict';

import { takeObsidianImportRequest, withObsidianImportRequest } from '../../app/static/js/modules/import-on-open.js';

// Creating a vault with "Import an Obsidian vault into it" (PLAN.md, slice 1b): the request
// travels in the new vault's address and is taken out once read.

function fakeWindow(address) {
    const url = new URL(address);
    const replaced = [];
    globalThis.window = {
        location: { hash: url.hash, pathname: url.pathname, search: url.search },
        history: { state: { kept: true }, replaceState: (state, title, path) => replaced.push({ state, path }) },
    };
    return replaced;
}

test('the new vault\'s address carries the request', () => {
    assert.equal(withObsidianImportRequest('https://127.0.0.1:8444/'), 'https://127.0.0.1:8444/#import-obsidian');
    assert.equal(withObsidianImportRequest('https://127.0.0.1:8444/?x=1#old'), 'https://127.0.0.1:8444/?x=1#import-obsidian');
});

test('the request is read once and taken out of the address', () => {
    const replaced = fakeWindow('https://127.0.0.1:8444/?x=1#import-obsidian');
    assert.equal(takeObsidianImportRequest(), true);
    assert.deepEqual(replaced, [{ state: { kept: true }, path: '/?x=1' }]);
});

test('an address without the request opens nothing and is left alone', () => {
    const replaced = fakeWindow('https://127.0.0.1:8444/#other');
    assert.equal(takeObsidianImportRequest(), false);
    assert.deepEqual(replaced, []);
    delete globalThis.window;
});
