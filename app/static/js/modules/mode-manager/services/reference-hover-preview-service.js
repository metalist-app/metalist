import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { isReferenceSuggestionListOpen } from './reference-suggestions-service.js';
import { PREVIEW_OWNERS, hideReferencePreview, showReferencePreview } from './reference-preview-card-service.js';

// A link's preview card (docs/ui/references.md, "Preview"; agreed 2026-10-26): the
// pointer resting on a reference shows the card of the note it names, just below
// that line (above it near the window's bottom), from the link's left edge. In the
// note being edited that is its `[[UUID]]` or `![[UUID]]`, brackets included;
// elsewhere a link (an embed already shows its note). Passing over without
// stopping shows nothing; moving off, typing, a click or a scroll hides it. While
// the `[[` list is open only its own card shows. Only a mouse rests: touch shows none.

// How long the pointer rests on a reference before its card shows.
const HOVER_DELAY_MS = 300;
// Between the reference's line and the card, as between a `[[` and its list.
const GAP_PX = 6;
const MOUSE = 'mouse';
const REFERENCE_RE = /!?\[\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\]/g;
const LINK_SELECTOR = '.note-reference-block.note-reference-note.note-reference-link-mode[data-ref-note-id]';
const EDITED_CONTENT_SELECTOR = '.note.editing > .note-content';

const moduleState = ApplicationState.createFields('reference-hover-preview-service', {
    initialized: false,
    // The reference under the pointer: its note, the link or text node it is in and
    // where in that node it starts, and the box of its line under the pointer.
    target: null,
    timer: null,
});

function setState(field, value) {
    if (!stateValuesEqual(moduleState[field], value)) moduleState[field] = value;
}

function contains(rect, x, y) {
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

// The box of the reference's line under the pointer, or null when the pointer is past it.
function lineUnder(rects, x, y) {
    const hit = [...rects].find((rect) => contains(rect, x, y));
    if (hit === undefined) return null;
    return { left: hit.left, top: hit.top, bottom: hit.bottom };
}

// `[[UUID]]` or `![[UUID]]` under the pointer in the text being edited.
function editedReferenceAt(content, x, y) {
    const position = document.caretPositionFromPoint(x, y);
    if (position === null || !(position.offsetNode instanceof Text) || !content.contains(position.offsetNode)) return null;
    const node = position.offsetNode;
    for (const match of node.data.matchAll(REFERENCE_RE)) {
        const start = match.index;
        const end = start + match[0].length;
        if (position.offset < start || position.offset > end) continue;
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, end);
        const line = lineUnder(range.getClientRects(), x, y);
        if (line === null) return null;
        return { noteId: match[1], anchor: node, start, line };
    }
    return null;
}

function referenceAt(event) {
    if (!(event.target instanceof Element)) return null;
    const content = event.target.closest(EDITED_CONTENT_SELECTOR);
    if (content !== null) return editedReferenceAt(content, event.clientX, event.clientY);
    const link = event.target.closest(LINK_SELECTOR);
    if (link === null) return null;
    const line = lineUnder(link.getClientRects(), event.clientX, event.clientY);
    if (line === null) return null;
    return { noteId: link.dataset.refNoteId, anchor: link, start: 0, line };
}

function isSameReference(first, second) {
    return first !== null && second !== null && first.anchor === second.anchor && first.start === second.start;
}

function placeBelow(line) {
    return (card) => {
        const { width, height } = card.getBoundingClientRect();
        const left = Math.max(0, Math.min(line.left, window.innerWidth - width));
        let top = line.bottom + GAP_PX;
        if (top + height > window.innerHeight) top = line.top - GAP_PX - height;
        card.style.left = `${left}px`;
        card.style.top = `${top}px`;
    };
}

function dismiss() {
    if (moduleState.timer !== null) {
        clearTimeout(moduleState.timer);
        setState('timer', null);
    }
    setState('target', null);
    hideReferencePreview(PREVIEW_OWNERS.hover);
}

function showTarget() {
    setState('timer', null);
    const target = moduleState.target;
    void showReferencePreview(target.noteId, placeBelow(target.line), PREVIEW_OWNERS.hover);
}

function handlePointerMove(event) {
    if (event.pointerType !== MOUSE) return;
    if (isReferenceSuggestionListOpen()) {
        dismiss();
        return;
    }
    const target = referenceAt(event);
    if (isSameReference(target, moduleState.target)) return;
    dismiss();
    if (target === null) return;
    setState('target', target);
    setState('timer', setTimeout(showTarget, HOVER_DELAY_MS));
}

function handlePointerOut(event) {
    if (event.relatedTarget === null) dismiss();
}

export function initializeReferenceHoverPreviews() {
    if (moduleState.initialized) return;
    setState('initialized', true);
    document.addEventListener('pointermove', handlePointerMove, { passive: true });
    document.addEventListener('pointerout', handlePointerOut, { passive: true });
    for (const type of ['keydown', 'mousedown', 'wheel']) window.addEventListener(type, dismiss, { capture: true, passive: true });
    document.addEventListener('scroll', dismiss, { capture: true, passive: true });
    window.addEventListener('blur', dismiss);
}
