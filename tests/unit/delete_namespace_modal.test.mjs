import assert from 'node:assert/strict';
import test from 'node:test';

import {
    extractDeletableNamespaceNames,
    validateNamespaceDeletionSubmission,
} from '../../app/static/js/modules/modals/delete-namespace-validation.js';


test('extractDeletableNamespaceNames builds the server-provided selection list', () => {
    const names = extractDeletableNamespaceNames({
        namespaces: [
            { namespace: 'default' },
            { namespace: 'cla' },
            { namespace: 'thomas' },
        ],
    });

    assert.deepEqual(names, ['default', 'cla', 'thomas']);
});


test('extractDeletableNamespaceNames rejects malformed catalog entries', () => {
    assert.throws(
        () => extractDeletableNamespaceNames({ namespaces: [{ namespace: '' }] }),
        /namespace name/,
    );
});


test('validateNamespaceDeletionSubmission requires the exact namespace name', () => {
    assert.throws(
        () => validateNamespaceDeletionSubmission({
            namespace: 'work',
            confirmationText: 'delete',
            isCurrentNamespace: true,
            redirectNamespace: 'default',
        }),
        /Type work to confirm the deletion\.$/,
    );
});


test('validateNamespaceDeletionSubmission never requires a namespace password', () => {
    const payload = validateNamespaceDeletionSubmission({
        namespace: 'work',
        confirmationText: ' work ',
        isCurrentNamespace: true,
        redirectNamespace: 'cla',
    });

    assert.deepEqual(payload, {
        confirmed_namespace: 'work',
        redirect_namespace: 'cla',
    });
});


test('validateNamespaceDeletionSubmission allows deleting default', () => {
    const payload = validateNamespaceDeletionSubmission({
        namespace: 'default',
        confirmationText: 'default',
        isCurrentNamespace: true,
        redirectNamespace: 'default',
    });

    assert.deepEqual(payload, {
        confirmed_namespace: 'default',
        redirect_namespace: 'default',
    });
});


test('validateNamespaceDeletionSubmission requires an active-namespace redirect', () => {
    assert.throws(
        () => validateNamespaceDeletionSubmission({
            namespace: 'work',
            confirmationText: 'work',
            isCurrentNamespace: true,
            redirectNamespace: '',
        }),
        /Choose where MetaList goes after the deletion\.$/,
    );
});
