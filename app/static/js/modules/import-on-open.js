// Creating a vault can ask for an Obsidian import in it (PLAN.md, slice 1b): the new
// vault's address carries the request as #import-obsidian, and the new vault, once open,
// takes it out of the address (so a reload doesn't ask again) and opens the import dialog.

const OBSIDIAN_IMPORT_FRAGMENT = 'import-obsidian';
const FRAGMENT_MARK = '#';

/** The address of a vault, asking it to open the Obsidian import once it has opened. */
export function withObsidianImportRequest(address) {
    if (typeof address !== 'string' || address === '') {
        throw new Error('withObsidianImportRequest requires an address');
    }
    const url = new URL(address);
    url.hash = OBSIDIAN_IMPORT_FRAGMENT;
    return url.toString();
}

/** Whether this page's address asks for the Obsidian import; the request is removed from it. */
export function takeObsidianImportRequest() {
    if (window.location.hash !== FRAGMENT_MARK + OBSIDIAN_IMPORT_FRAGMENT) {
        return false;
    }
    window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
    return true;
}
