import { ApplicationState } from '../../application-state.js';

// Whether the Virtual Folders tree shows (an experiment: virtual-folders-service.js), apart
// so the command palette's labels can read it without the tree's dependencies. The tree's
// service keeps it in this browser's storage.

const moduleState = ApplicationState.createFields('virtual-folders-state', {
    isShown: false,
});

// Whether the tree shows, remembered by this browser (the maintainer, 2026-11-01: the choice
// stays across logins). Not a vault preference: a MetaList that doesn't know a stored
// preference refuses to load them, so dropping the experiment would leave a vault older
// MetaLists can't open.
export const VIRTUAL_FOLDERS_SHOWN_KEY = 'metalist.virtual_folders.shown';
export const VIRTUAL_FOLDERS_SHOWN = 'true';
export const VIRTUAL_FOLDERS_HIDDEN = 'false';

/** The stored switch: main.js reads it before any request, and every request sends it
 * (session-auth.js), so a search context's folder applies only while this browser's tree is
 * open (docs/ready-to-build/virtual-folders.md, the folder tree switch), from the first view after a reload. */
export function storedVirtualFoldersShown() {
    return window.localStorage.getItem(VIRTUAL_FOLDERS_SHOWN_KEY) === VIRTUAL_FOLDERS_SHOWN;
}

export function isVirtualFoldersShown() {
    return moduleState.isShown;
}

export function rememberVirtualFoldersShown(isShown) {
    if (typeof isShown !== 'boolean') {
        throw new Error('rememberVirtualFoldersShown requires a boolean');
    }
    if (moduleState.isShown !== isShown) moduleState.isShown = isShown;
}
