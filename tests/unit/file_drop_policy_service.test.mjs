import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldCreateTopNoteForFileDrop } from '../../app/static/js/modules/mode-manager/services/file-drop-policy-service.js';

test('a drop outside the note being edited makes new notes', () => {
    assert.equal(shouldCreateTopNoteForFileDrop({
        isEditing: true, currentNoteId: 'new-note', hasEditingDropTarget: false,
    }), true);
});

test('a drop on the note being edited goes in it', () => {
    assert.equal(shouldCreateTopNoteForFileDrop({
        isEditing: true, currentNoteId: 'new-note', hasEditingDropTarget: true,
    }), false);
});

test('a drop with no note being edited makes new notes', () => {
    assert.equal(shouldCreateTopNoteForFileDrop({
        isEditing: false, currentNoteId: null, hasEditingDropTarget: false,
    }), true);
});

test('rejects editing state without a current note id', () => {
    assert.throws(
        () => shouldCreateTopNoteForFileDrop({ isEditing: true, currentNoteId: null, hasEditingDropTarget: false }),
        /requires currentNoteId while editing/,
    );
});
