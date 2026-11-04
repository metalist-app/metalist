import { ApplicationState } from '../../application-state.js';

// Whether the Virtual Folders tree shows (an experiment: virtual-folders-service.js), apart
// so the command palette's labels can read it without the tree's dependencies. The tree's
// service keeps it in this browser's storage.

const moduleState = ApplicationState.createFields('virtual-folders-state', {
    isShown: false,
});

export function isVirtualFoldersShown() {
    return moduleState.isShown;
}

export function rememberVirtualFoldersShown(isShown) {
    if (typeof isShown !== 'boolean') {
        throw new Error('rememberVirtualFoldersShown requires a boolean');
    }
    if (moduleState.isShown !== isShown) moduleState.isShown = isShown;
}
