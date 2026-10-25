import assert from 'node:assert/strict';
import test from 'node:test';

import { AUTOSAVE_STATUS } from '../../app/static/js/modules/excalidraw/excalidraw-autosave.js';
import { diagramStatusShown } from '../../app/static/js/modules/excalidraw/excalidraw-status-shown.js';

// The diagram editor's bar keeps its ordinary save states; a problem leaves it for a lasting
// corner card (a failed save, retried, which becomes a dialog after 30 s) or a dialog (a save
// another window made impossible). Agreed 2026-10-25, step 5c.

test('the bar keeps the ordinary save states', () => {
    assert.deepEqual(diagramStatusShown(AUTOSAVE_STATUS.SAVED), { bar: 'All changes saved', problem: 'none' });
    assert.deepEqual(diagramStatusShown(AUTOSAVE_STATUS.UNSAVED), { bar: 'Unsaved changes', problem: 'none' });
    assert.deepEqual(diagramStatusShown(AUTOSAVE_STATUS.SAVING), { bar: 'Saving…', problem: 'none' });
});

test('a failed save is retried in a corner card, the bar saying the changes are unsaved', () => {
    assert.deepEqual(diagramStatusShown(AUTOSAVE_STATUS.ERROR), { bar: 'Unsaved changes', problem: 'retrying' });
});

test('a save another window made impossible is a dialog', () => {
    assert.deepEqual(diagramStatusShown(AUTOSAVE_STATUS.CONFLICT), { bar: 'Not saved', problem: 'conflict' });
});
