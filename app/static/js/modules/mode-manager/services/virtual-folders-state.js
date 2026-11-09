import { ApplicationState } from '../../application-state.js';

// Whether the Virtual Folders tree shows (an experiment: virtual-folders-service.js), apart
// so the command palette's labels can read it without the tree's dependencies. It shows while
// a folder context does (docs/ready-to-build/virtual-folders.md, "Folder contexts", 2026-11-07); until then the
// choice was kept in this browser's storage (metalist.virtual_folders.shown, now read by nothing).

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
