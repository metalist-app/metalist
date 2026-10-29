import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { CommandGate } from './command-gate-service.js';
import { actionDeselectNote } from '../actions/selection-actions.js';
import { actionExitSearchMode } from '../actions/search-actions.js';
import { actionRefreshAndMaybeSelect } from '../actions/ui-actions.js';
import { FilesAPI } from '../../api-client.js';
import { FileRenameModal } from '../../modals/file-rename-modal.js';

// Rename File… from a file card's, picture's or diagram's menu (docs/ui/references.md).
// The new name shows on every card of the file and is what its downloads save as.

const moduleState = ApplicationState.createFields('file-rename-service', {
    modal: null,
});

function renameModal() {
    if (moduleState.modal === null) {
        moduleState.modal = new FileRenameModal();
    }
    return moduleState.modal;
}

export async function renameFileFromMenu(fileId) {
    if (typeof fileId !== 'string' || fileId === '') {
        throw new Error('renameFileFromMenu requires fileId');
    }
    if (ModeContext.isLoading || ModeContext.modalStack.length > 0) {
        return;
    }
    // Like every dialog, it saves the edited note and leaves edit mode first.
    if (ModeContext.isSearching) {
        actionExitSearchMode();
    }
    if (ModeContext.isEditing) {
        const left = await CommandGate.run('contextMenu.file.rename.exit_editing', async () => {
            await actionDeselectNote();
        });
        if (left === null) {
            return;
        }
    }
    const name = await FilesAPI.getFileName(fileId);
    const newName = await renameModal().openForFile({ fileId, name });
    if (newName === null) {
        return;
    }
    await CommandGate.run('contextMenu.file.rename', async () => {
        await FilesAPI.renameFile(fileId, newName);
        await actionRefreshAndMaybeSelect({ context: 'renameFile' });
    });
}
