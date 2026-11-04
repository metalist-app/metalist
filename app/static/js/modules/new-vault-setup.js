// Setting up a new vault (PLAN.md, phase 2): Create Vault is the new vault wizard's first
// step, and the new vault's address asks it to go on with the rest once it has opened
// (#setup=wizard). The step is taken out of the address as it starts, so a reload never
// repeats it.

const SETUP_PREFIX = 'setup=';
const STEP_SEPARATOR = '+';
const FRAGMENT_MARK = '#';
// The new vault wizard, from its Password step on (wizard/setup-wizards.js).
export const VAULT_WIZARD_STEP = 'wizard';

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
