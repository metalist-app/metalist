import assert from 'node:assert/strict';
import test from 'node:test';

import { ApplicationState } from '../../app/static/js/modules/application-state.js';
import { keepSavedView } from '../../app/static/js/modules/excalidraw/excalidraw-kept-view.js';

function editorSession(keptView) {
    return ApplicationState.createFields('excalidraw-editor-session', { keptView });
}

test('a second autosave with the view unmoved keeps the view without a redundant change', () => {
    const session = editorSession(null);
    keepSavedView(session, { centerX: 250, centerY: 150, zoom: 2 });
    // The next edit is saved in the same view: viewOfAppState returns an equal, new object.
    keepSavedView(session, { centerX: 250, centerY: 150, zoom: 2 });
    assert.deepEqual(session.keptView, { centerX: 250, centerY: 150, zoom: 2 });
});

test('the first autosave in the view the editor opened in keeps it without a redundant change', () => {
    const session = editorSession({ centerX: 60, centerY: 35, zoom: 1 });
    keepSavedView(session, { centerX: 60, centerY: 35, zoom: 1 });
    assert.deepEqual(session.keptView, { centerX: 60, centerY: 35, zoom: 1 });
});

test('a save after panning or zooming keeps the new view', () => {
    const session = editorSession({ centerX: 60, centerY: 35, zoom: 1 });
    keepSavedView(session, { centerX: 400, centerY: 35, zoom: 1 });
    assert.deepEqual(session.keptView, { centerX: 400, centerY: 35, zoom: 1 });
    keepSavedView(session, { centerX: 400, centerY: 35, zoom: 1.5 });
    assert.deepEqual(session.keptView, { centerX: 400, centerY: 35, zoom: 1.5 });
});
