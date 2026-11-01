import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    VAULT_WIZARD_STEP, readSetupSteps, withSetupSteps, writeSetupSteps,
} from '../../app/static/js/modules/new-vault-setup.js';

// Setting up a new vault (PLAN.md, phase 2): Create Vault's address asks the new vault to go
// on with the wizard, and the step leaves the address as it starts, so a reload never
// repeats it.

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

test('the new vault\'s address asks for the wizard, and for nothing with no step', () => {
    assert.equal(withSetupSteps('https://127.0.0.1:8444/', [VAULT_WIZARD_STEP]), 'https://127.0.0.1:8444/#setup=wizard');
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

test('an address with another fragment asks for nothing', () => {
    fakeWindow('https://127.0.0.1:8444/#other');
    assert.deepEqual(readSetupSteps(), []);
    delete globalThis.window;
});
