import { AUTOSAVE_STATUS } from './excalidraw-autosave.js';

// How each autosave status shows (docs/ui/excalidraw.md): the editor's bar keeps the ordinary
// states; a problem leaves it, for a lasting corner card (a failed save, retried) or a dialog
// (a save another window made impossible).
const STATUS_SHOWN = Object.freeze({
    [AUTOSAVE_STATUS.SAVED]: { bar: 'All changes saved', problem: 'none' },
    [AUTOSAVE_STATUS.UNSAVED]: { bar: 'Unsaved changes', problem: 'none' },
    [AUTOSAVE_STATUS.SAVING]: { bar: 'Saving…', problem: 'none' },
    [AUTOSAVE_STATUS.ERROR]: { bar: 'Unsaved changes', problem: 'retrying' },
    [AUTOSAVE_STATUS.CONFLICT]: { bar: 'Not saved', problem: 'conflict' },
});

export function diagramStatusShown(status) {
    if (!Object.hasOwn(STATUS_SHOWN, status)) {
        throw new Error(`Unknown diagram autosave status: ${status}`);
    }
    return STATUS_SHOWN[status];
}
