import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    AI_STEP, PASSWORD_STEP, importSourceOfStep, importStep, readSetupSteps, withSetupSteps, writeSetupSteps,
} from '../../app/static/js/modules/new-vault-setup.js';

// Setting up a new vault (PLAN.md, slice 1d): the steps Create Vault asked for travel in the
// new vault's address and leave it one by one, so a reload never repeats a finished one.

function fakeWindow(address) {
    const url = new URL(address);
    globalThis.window = {
        location: { hash: url.hash, pathname: url.pathname, search: url.search },
        history: {
            state: { kept: true },
            replaceState: (state, title, path) => {
                assert.deepEqual(state, { kept: true });
                const next = new URL(path, url);
                globalThis.window.location.hash = next.hash;
            },
        },
    };
}

test('the new vault\'s address carries the steps in order, and nothing with none', () => {
    const steps = [PASSWORD_STEP, AI_STEP, importStep('obsidian')];
    assert.equal(withSetupSteps('https://127.0.0.1:8444/', steps), 'https://127.0.0.1:8444/#setup=password+ai+import-obsidian');
    assert.equal(withSetupSteps('https://127.0.0.1:8444/', []), 'https://127.0.0.1:8444/');
});

test('the steps are read back and leave the address one by one', () => {
    fakeWindow('https://127.0.0.1:8444/?x=1#setup=password+ai+import-markdown');
    assert.deepEqual(readSetupSteps(), ['password', 'ai', 'import-markdown']);
    writeSetupSteps(['ai', 'import-markdown']);
    assert.deepEqual(readSetupSteps(), ['ai', 'import-markdown']);
    writeSetupSteps([]);
    assert.equal(window.location.hash, '');
    assert.deepEqual(readSetupSteps(), []);
    delete globalThis.window;
});

test('an import step names its source', () => {
    assert.equal(importSourceOfStep(importStep('markdown')), 'markdown');
    assert.equal(importSourceOfStep(AI_STEP), null);
});

test('an address with another fragment asks for nothing', () => {
    fakeWindow('https://127.0.0.1:8444/#other');
    assert.deepEqual(readSetupSteps(), []);
    delete globalThis.window;
});
