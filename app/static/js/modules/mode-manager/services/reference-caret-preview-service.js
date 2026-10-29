import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { half } from '../../half.js';
import { unlessDiagramEditorOpen } from '../../excalidraw/excalidraw-editor-state.js';
import { isReferenceSuggestionListOpen } from './reference-suggestions-service.js';
import {
    PREVIEW_OWNERS, hideReferencePreview, isReferencePreviewShownBy, showReferencePreview,
} from './reference-preview-card-service.js';
import { REFERENCE_RE, placeBelow } from './reference-hover-preview-service.js';

// The card for the reference the caret is in (docs/ui/references.md, "The preview card";
// smart previews, slice 4, agreed 2026-10-29): with the caret inside `[[UUID]]` or
// `![[UUID]]` of the note being edited (its `|text` and brackets included), the card the
// pointer shows on it, for a note or a file, just below that line from the reference's
// left edge. Moving within the reference keeps it; leaving hides it; selecting text keeps
// it; Escape hides it, and editing goes on, until the caret leaves the reference; scrolling
// hides it until the caret moves. Part of Previews While Editing; the phone has none.

const EDITED_CONTENT_SELECTOR = '.note.editing > .note-content';
const PREVIEWS_ON_CLASS = 'pref-edit-previews';
const PHONE_CLASS = 'phone-layout';
// The card asks once the caret has stopped this long, as the formula preview does.
const CARET_PAUSE_MS = 150;

const moduleState = ApplicationState.createFields('reference-caret-preview-service', {
    initialized: false,
    timer: null,
    // The reference whose card was asked for: its text node and where in it it starts.
    reference: null,
    // Escape hid its card; it stays hidden until the caret leaves the reference.
    isDismissed: false,
});

function setState(field, value) {
    if (!stateValuesEqual(moduleState[field], value)) moduleState[field] = value;
}

function isEnabled() {
    return document.body.classList.contains(PREVIEWS_ON_CLASS) && !document.body.classList.contains(PHONE_CLASS);
}

function editedElementOf(node) {
    const element = node instanceof Element ? node : node.parentElement;
    if (element === null) return null;
    return element.closest(EDITED_CONTENT_SELECTOR);
}

function isSelectingInEditedNote() {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || selection.isCollapsed) return false;
    return editedElementOf(selection.anchorNode) !== null;
}

// The box of the reference on the caret's line: the reference's left edge there, the line's top and bottom.
function lineOf(node, start, end, caretBox) {
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, end);
    const middle = caretBox.top + half(caretBox.bottom - caretBox.top);
    const onCaretLine = [...range.getClientRects()].find((box) => box.top <= middle && middle <= box.bottom);
    if (onCaretLine === undefined) return { left: caretBox.left, top: caretBox.top, bottom: caretBox.bottom };
    return { left: onCaretLine.left, top: onCaretLine.top, bottom: onCaretLine.bottom };
}

// The reference the caret is inside, between its first and last character, or null.
function referenceAtCaret() {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const node = range.startContainer;
    if (!(node instanceof Text) || editedElementOf(node) === null) return null;
    const offset = range.startOffset;
    for (const match of node.data.matchAll(REFERENCE_RE)) {
        const start = match.index;
        const end = start + match[0].length;
        if (offset <= start || offset >= end) continue;
        const caretBoxes = range.getClientRects();
        if (caretBoxes.length === 0) return null;
        return { node, start, noteId: match[1], line: lineOf(node, start, end, caretBoxes[0]) };
    }
    return null;
}

function isSameReference(first, second) {
    return first !== null && second !== null && first.node === second.node && first.start === second.start;
}

function forget() {
    setState('reference', null);
    setState('isDismissed', false);
    hideReferencePreview(PREVIEW_OWNERS.caret);
}

function checkCaret() {
    setState('timer', null);
    if (isSelectingInEditedNote()) return;
    const reference = referenceAtCaret();
    if (!isEnabled() || reference === null || isReferenceSuggestionListOpen()) {
        forget();
        return;
    }
    if (isSameReference(reference, moduleState.reference)) return;
    setState('reference', reference);
    setState('isDismissed', false);
    void showReferencePreview(reference.noteId, placeBelow(reference.line), PREVIEW_OWNERS.caret);
}

function scheduleCheck() {
    if (moduleState.timer !== null) clearTimeout(moduleState.timer);
    setState('timer', setTimeout(checkCaret, CARET_PAUSE_MS));
}

// Escape hides only the card; editing goes on.
function handleKeyDown(event) {
    if (event.key !== 'Escape' || !isReferencePreviewShownBy(PREVIEW_OWNERS.caret)) return;
    event.preventDefault();
    event.stopPropagation();
    setState('isDismissed', true);
    hideReferencePreview(PREVIEW_OWNERS.caret);
}

// A scroll hides it; the next caret move asks again.
function handleScroll() {
    if (moduleState.isDismissed) return;
    setState('reference', null);
    hideReferencePreview(PREVIEW_OWNERS.caret);
}

export function initializeReferenceCaretPreviews() {
    if (moduleState.initialized) return;
    setState('initialized', true);
    document.addEventListener('selectionchange', unlessDiagramEditorOpen(scheduleCheck));
    document.addEventListener('input', unlessDiagramEditorOpen(scheduleCheck), { capture: true });
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    document.addEventListener('scroll', handleScroll, { capture: true, passive: true });
}
