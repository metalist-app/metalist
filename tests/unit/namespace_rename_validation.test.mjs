import assert from 'node:assert/strict';
import test from 'node:test';

import { buildNamespaceRenamePayload, vaultNameProblem } from '../../app/static/js/modules/modals/namespace-rename-validation.js';


test('buildNamespaceRenamePayload accepts a new non-overlapping name', () => {
    assert.deepEqual(
        buildNamespaceRenamePayload({
            currentNamespace: 'default',
            targetNamespace: 'personal',
            existingNamespaces: ['default', 'work'],
        }),
        { target_namespace: 'personal' },
    );
});


test('buildNamespaceRenamePayload rejects an existing namespace', () => {
    assert.throws(
        () => buildNamespaceRenamePayload({
            currentNamespace: 'default',
            targetNamespace: 'work',
            existingNamespaces: ['default', 'work'],
        }),
        /already exists/,
    );
});


test('buildNamespaceRenamePayload rejects invalid namespace syntax', () => {
    assert.throws(
        () => buildNamespaceRenamePayload({
            currentNamespace: 'default',
            targetNamespace: 'Personal Stuff',
            existingNamespaces: ['default'],
        }),
        /lowercase letters/,
    );
});


test('vaultNameProblem says what is wrong with a vault name, for the user', () => {
    const existingNamespaces = ['default', 'work'];
    const problem = (name, currentNamespace) => vaultNameProblem({ name, existingNamespaces, currentNamespace });
    assert.equal(problem('', null), 'Enter a vault name.');
    assert.equal(problem('Bad Name', null), 'A vault name may use only lowercase letters, digits and -.');
    assert.equal(problem('work', null), 'That vault already exists. Pick another name.');
    assert.equal(problem('default', 'default'), "That is the vault's current name. Pick another name.");
    assert.equal(problem('personal', 'default'), '');
});
