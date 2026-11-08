import assert from 'node:assert/strict';
import test from 'node:test';

import { importFinishedMessage } from '../../app/static/js/modules/wizard/import-finished-message.js';


test('an import says how many notes came in and the folder they went into', () => {
    assert.equal(importFinishedMessage(340, 'My-Vault/'), 'Imported 340 notes into My-Vault/.');
    assert.equal(importFinishedMessage(1, 'My-Vault/'), 'Imported 1 note into My-Vault/.');
});


test('an import with no folder of its own says only how many notes came in', () => {
    assert.equal(importFinishedMessage(340, ''), 'Imported 340 notes.');
    assert.equal(importFinishedMessage(1, ''), 'Imported 1 note.');
});
