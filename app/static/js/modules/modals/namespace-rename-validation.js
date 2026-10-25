import { UserInputRejected } from '../expected-errors.js';

const NAMESPACE_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;


// What is wrong with a vault name, said for the user, or '' when nothing is. A new vault
// has no current name (null).
export function vaultNameProblem({ name, existingNamespaces, currentNamespace }) {
    if (typeof name !== 'string') {
        throw new Error('vaultNameProblem requires the name');
    }
    if (!Array.isArray(existingNamespaces)) {
        throw new Error('vaultNameProblem requires the existing vaults');
    }
    if (currentNamespace !== null && (typeof currentNamespace !== 'string' || currentNamespace.length === 0)) {
        throw new Error('vaultNameProblem requires the current vault name or null');
    }
    if (name.length === 0) {
        return 'Enter a vault name.';
    }
    if (!NAMESPACE_PATTERN.test(name)) {
        return 'A vault name may use only lowercase letters, digits and -.';
    }
    if (name === currentNamespace) {
        return "That is the vault's current name. Pick another name.";
    }
    if (existingNamespaces.includes(name)) {
        return 'That vault already exists. Pick another name.';
    }
    return '';
}


export function buildNamespaceRenamePayload({
    currentNamespace,
    targetNamespace,
    existingNamespaces,
}) {
    if (typeof currentNamespace !== 'string' || currentNamespace.length === 0) {
        throw new Error('Current namespace is required');
    }
    if (typeof targetNamespace !== 'string') {
        throw new Error('New namespace name is required');
    }
    const normalizedTarget = targetNamespace.trim();
    const problem = vaultNameProblem({ name: normalizedTarget, existingNamespaces, currentNamespace });
    if (problem !== '') {
        throw new UserInputRejected(problem);
    }
    return { target_namespace: normalizedTarget };
}
