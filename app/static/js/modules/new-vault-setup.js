// Setting up a new vault (PLAN.md, slice 1d): Create Vault asks whether to add a password,
// set up AI and import something, and the new vault's address carries the answers as steps
// (#setup=password+ai+import-obsidian). The new vault, once open, runs them in that order,
// taking each out of the address as it starts, so the reload that adding a password brings
// (and the login after it) goes on with the steps left, and no reload repeats one.

const SETUP_PREFIX = 'setup=';
const STEP_SEPARATOR = '+';
const FRAGMENT_MARK = '#';
const IMPORT_STEP_PREFIX = 'import-';
export const PASSWORD_STEP = 'password';
export const AI_STEP = 'ai';

/** The step that imports from an import source (import-sources.js). */
export function importStep(sourceKey) {
    if (typeof sourceKey !== 'string' || sourceKey === '') {
        throw new Error('importStep requires a source key');
    }
    return IMPORT_STEP_PREFIX + sourceKey;
}

/** The import source an import step names; null for any other step. */
export function importSourceOfStep(step) {
    if (!step.startsWith(IMPORT_STEP_PREFIX)) {
        return null;
    }
    return step.slice(IMPORT_STEP_PREFIX.length);
}

/** A vault's address, asking it to run steps once it has opened (unchanged with none). */
export function withSetupSteps(address, steps) {
    if (typeof address !== 'string' || address === '' || !Array.isArray(steps)) {
        throw new Error('withSetupSteps requires an address and a list of steps');
    }
    if (steps.length === 0) {
        return address;
    }
    const url = new URL(address);
    url.hash = SETUP_PREFIX + steps.join(STEP_SEPARATOR);
    return url.toString();
}

/** The steps this page's address still asks for, in order. */
export function readSetupSteps() {
    const hash = window.location.hash;
    if (!hash.startsWith(FRAGMENT_MARK + SETUP_PREFIX)) {
        return [];
    }
    return hash.slice(FRAGMENT_MARK.length + SETUP_PREFIX.length).split(STEP_SEPARATOR).filter((step) => step !== '');
}

/** Leave only steps in this page's address (none: no setup in it at all). */
export function writeSetupSteps(steps) {
    let address = window.location.pathname + window.location.search;
    if (steps.length > 0) {
        address += FRAGMENT_MARK + SETUP_PREFIX + steps.join(STEP_SEPARATOR);
    }
    window.history.replaceState(window.history.state, '', address);
}
