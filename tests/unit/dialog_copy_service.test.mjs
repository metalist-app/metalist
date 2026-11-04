import { test } from 'node:test';
import assert from 'node:assert/strict';

import { isCopyOfDialogSelection } from '../../app/static/js/modules/mode-manager/services/dialog-copy-service.js';

const TEXT_NODE = 3;

function element(isInDialog) {
    return { nodeType: 1, closest: (selector) => (selector === '.modal' && isInDialog ? {} : null) };
}

function textIn(parent) {
    return { nodeType: TEXT_NODE, parentElement: parent };
}

function selection(anchorNode, focusNode, isCollapsed) {
    return { anchorNode, focusNode, isCollapsed };
}

// The import wizard's text could not be copied (the maintainer, 2026-11-01): the open
// dialog's key gate swallowed Cmd+C, as selecting text leaves the focus on the page.
test('Cmd/Ctrl+C on text selected in a dialog is the browser\'s copy', () => {
    const dialogText = textIn(element(true));
    assert.equal(isCopyOfDialogSelection({ shortcutKey: 'c', metaOrCtrl: true, selection: selection(dialogText, dialogText, false) }), true);
    assert.equal(isCopyOfDialogSelection({
        shortcutKey: 'c', metaOrCtrl: true, selection: selection(element(true), textIn(element(true)), false),
    }), true);
});

test('anything else stays gated: no selection, a selection outside the dialog, another key, C alone', () => {
    const dialogText = textIn(element(true));
    const pageText = textIn(element(false));
    assert.equal(isCopyOfDialogSelection({ shortcutKey: 'c', metaOrCtrl: true, selection: selection(dialogText, dialogText, true) }), false);
    assert.equal(isCopyOfDialogSelection({ shortcutKey: 'c', metaOrCtrl: true, selection: selection(pageText, dialogText, false) }), false);
    assert.equal(isCopyOfDialogSelection({ shortcutKey: 'v', metaOrCtrl: true, selection: selection(dialogText, dialogText, false) }), false);
    assert.equal(isCopyOfDialogSelection({ shortcutKey: 'c', metaOrCtrl: false, selection: selection(dialogText, dialogText, false) }), false);
});
