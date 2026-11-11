import { ApplicationState } from '../../application-state.js';

// Whether the Virtual Folders tree shows (virtual-folders-service.js), apart so the command
// palette's labels and the import walkthrough can read it without the tree's dependencies. It
// belongs to the view, not a search context: the folders tab shows or hides it, switching contexts
// leaves it as it is, and the server keeps it with the tabs so a reload does too
// (docs/ready-to-build/folders-tab-and-multiple-folders.md §1; tab_state.py: treeShown). Every
// tab-state answer carries it.

const moduleState = ApplicationState.createFields('virtual-folders-state', {
    isShown: false,
});

export function isVirtualFoldersShown() {
    return moduleState.isShown;
}

/** answer.treeShown: whether the tree shows. */
export function recordTreeShownFromServer(answer) {
    if (answer === null || typeof answer !== 'object' || typeof answer.treeShown !== 'boolean') {
        throw new Error('The server\'s answer has no treeShown');
    }
    if (moduleState.isShown !== answer.treeShown) moduleState.isShown = answer.treeShown;
}
