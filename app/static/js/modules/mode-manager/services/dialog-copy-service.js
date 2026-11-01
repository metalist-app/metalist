// Copying text selected in a dialog (the import wizard's summary, an error's message) stays the
// browser's. Selecting static text leaves the focus on the page, not in the dialog, so the
// open dialog's key gate (keyboard-events.js) would otherwise swallow Cmd/Ctrl+C.

/**
 * Whether the key is Cmd/Ctrl+C (shortcutKey 'c' with metaOrCtrl) while selection, the page's
 * selection, holds text inside a dialog (.modal).
 */
export function isCopyOfDialogSelection({ shortcutKey, metaOrCtrl, selection }) {
    if (typeof shortcutKey !== 'string' || typeof metaOrCtrl !== 'boolean' || selection === null) {
        throw new Error('isCopyOfDialogSelection requires the shortcut key, metaOrCtrl and the selection');
    }
    if (shortcutKey !== 'c' || !metaOrCtrl || selection.isCollapsed) {
        return false;
    }
    return [selection.anchorNode, selection.focusNode].every((node) => isInDialog(node));
}

// Node.ELEMENT_NODE: a selection's ends are text nodes or elements.
const ELEMENT_NODE = 1;

function isInDialog(node) {
    if (node === null) return false;
    let element = node;
    if (node.nodeType !== ELEMENT_NODE) {
        element = node.parentElement;
    }
    return element !== null && element.closest('.modal') !== null;
}
