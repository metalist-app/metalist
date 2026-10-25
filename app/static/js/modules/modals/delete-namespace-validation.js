import { UserInputRejected } from '../expected-errors.js';

export function extractDeletableNamespaceNames(catalog) {
    if (!catalog || typeof catalog !== 'object') {
        throw new Error('Namespace catalog response is missing');
    }
    if (!Array.isArray(catalog.namespaces) || catalog.namespaces.length === 0) {
        throw new Error('Namespace catalog has no namespaces');
    }
    return catalog.namespaces.map((entry) => {
        if (!entry || typeof entry !== 'object') {
            throw new Error('Namespace catalog entry is invalid');
        }
        if (typeof entry.namespace !== 'string' || entry.namespace.length === 0) {
            throw new Error('Namespace catalog entry is missing namespace name');
        }
        return entry.namespace;
    });
}


export function validateNamespaceDeletionSubmission({
    namespace,
    confirmationText,
    isCurrentNamespace,
    redirectNamespace,
}) {
    if (typeof namespace !== 'string' || namespace.trim().length === 0) {
        throw new Error('Current namespace is unavailable');
    }
    if (typeof isCurrentNamespace !== 'boolean') {
        throw new Error('Current namespace state is unavailable');
    }
    if (typeof redirectNamespace !== 'string' || redirectNamespace.trim().length === 0) {
        throw new UserInputRejected('Choose where MetaList goes after the deletion.');
    }
    if (typeof confirmationText !== 'string') {
        throw new Error('validateNamespaceDeletionSubmission requires the confirmation text');
    }
    const normalizedConfirmationText = confirmationText.trim();
    if (normalizedConfirmationText !== namespace) {
        throw new UserInputRejected(`Type ${namespace} to confirm the deletion.`);
    }
    return {
        confirmed_namespace: normalizedConfirmationText,
        redirect_namespace: redirectNamespace.trim(),
    };
}
