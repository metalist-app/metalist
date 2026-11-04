import { half } from '../../half.js';

// Double-clicking a UUID in the text of a note being edited selects the whole UUID
// (b7414220-f998-45bc-b9f1-9d3a856e43c7), not the part between two dashes
// (docs/ui/references.md, agreed 2026-10-31). Inside `[[UUID]]` or `[[UUID|text]]` it is
// the UUID alone, as the tag bar's double-click selects a whole tag
// (tag-input-selection-service.js). Any other word keeps the browser's selection.

// A UUID with no letter or digit run on to either side.
const UUID_RE = /(?<![0-9A-Za-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9A-Za-z])/gi;

/** The UUID in text holding the place at index, as { start, end }, or null. */
export function uuidRangeAt(text, index) {
    if (typeof text !== 'string' || !Number.isInteger(index)) {
        throw new Error('uuidRangeAt requires text and an index');
    }
    for (const match of text.matchAll(UUID_RE)) {
        const end = match.index + match[0].length;
        if (match.index <= index && index < end) {
            return { start: match.index, end };
        }
    }
    return null;
}

export function selectUuidOnDoubleClick(event) {
    if (event.button !== 0) return;
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount !== 1) return;
    // The browser has selected the word under the pointer by now: a part of the UUID.
    const range = selection.getRangeAt(0);
    const node = range.startContainer;
    if (!(node instanceof Text) || range.endContainer !== node || range.collapsed) return;
    const parent = node.parentElement;
    if (parent === null) return;
    const content = parent.closest('.note-content');
    if (content === null || !content.isContentEditable) return;
    const uuid = uuidRangeAt(node.data, range.startOffset + Math.floor(half(range.endOffset - range.startOffset)));
    if (uuid === null) return;
    event.preventDefault();
    const whole = document.createRange();
    whole.setStart(node, uuid.start);
    whole.setEnd(node, uuid.end);
    selection.removeAllRanges();
    selection.addRange(whole);
}
