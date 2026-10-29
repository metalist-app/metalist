import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { half } from '../../half.js';
import { NotesAPI } from '../../api-client.js';
import { sanitizeNoteHtmlForStorage } from '../../note-html-sanitizer.js';
import { serverRenderedHtml } from '../../server-rendered-html.js';
import { unlessDiagramEditorOpen } from '../../excalidraw/excalidraw-editor-state.js';
import { getTagBarValue } from './tag-bar-service.js';
import { placePasteFormatOffer } from './paste-format-offer-service.js';
import { drawMermaidPreview, mermaidPreviewHtml } from './mermaid-render-service.js';

// Previews while editing (docs/ui/content-formatting.md, "Previews while editing";
// agreed 2026-10-29). With the caret inside a formula, a CSV table, a JSON value or a
// Mermaid diagram of the note being edited, a small panel just below that line, under the caret, shows it
// drawn; a table scrolls so the caret's row is in view, a diagram is scaled down to fit. The server finds what is under the caret and
// draws it as the note draws it (app/services/edit_previews.py), so a preview never
// disagrees with the note. The panel floats: the note's text never moves. While it is
// broken mid-typing the last good drawing fades toward a ghost; a pause shows why it is
// broken. Selecting text (to type over it) leaves it as it was. Escape hides it until the
// caret next leaves it; scrolling hides it until the next key or caret move.
// "Previews While Editing" turns it off; the phone has none.

// A Unicode noncharacter marks the caret; the server looks for the same one.
const CARET_MARK = '\ufdd0';
const EDITED_CONTENT_SELECTOR = '.note.editing > .note-content';
const PREVIEWS_ON_CLASS = 'pref-edit-previews';
const PHONE_CLASS = 'phone-layout';
const PREVIEW_NONE = 'none';
const PREVIEW_CSV = 'csv';
const PREVIEW_MERMAID = 'mermaid';
const PREVIEW_JSON = 'json';
const NO_CARET_ROW = -1;
// Tables, JSON and diagrams may be as wide as the window.
const WIDE_CLASS = 'edit-preview-wide';
const WIDE_KINDS = new Set([PREVIEW_CSV, PREVIEW_JSON, PREVIEW_MERMAID]);
const INVALID_DIAGRAM = 'Invalid Mermaid diagram';
// The panel's room (main.css, .edit-preview): this share of the window's height, and
// the window's width less this margin on each side.
const PANEL_HEIGHT_SHARE = 0.4;
const VIEWPORT_MARGIN_PX = 8;
const NO_SCALE_UP = 1;

// Tuning (the maintainer wants to try these before settling them):
// the preview asks once typing pauses this long, and draws a diagram (heavier) once it pauses this long,
const TYPING_PAUSE_MS = 150;
const DIAGRAM_PAUSE_MS = 400;
// a formula still broken after this pause shows why,
const BROKEN_PAUSE_MS = 1500;
// and the last good drawing fades over this long to this faint.
const FADE_MS = 600;
const GHOST_OPACITY = 0.25;
const FULL_OPACITY = 1;

const moduleState = ApplicationState.createFields('edit-preview-service', {
    initialized: false,
    panel: null,
    // Raised by every question asked, so an answer to a replaced question is dropped.
    requestSerial: 0,
    typingTimer: null,
    brokenTimer: null,
    drawTimer: null,
    // The note content the caret was last asked about: a caret in another note starts fresh.
    askedContent: null,
    // What is under the caret as it last rendered ({ kind, html, caretRow }), while the caret stays in it.
    lastGood: null,
    // Escape hid the panel; it stays hidden until the caret leaves the formula.
    isDismissed: false,
});

function setState(field, value) {
    if (!stateValuesEqual(moduleState[field], value)) moduleState[field] = value;
}

function isEnabled() {
    return document.body.classList.contains(PREVIEWS_ON_CLASS) && !document.body.classList.contains(PHONE_CLASS);
}

// The note being edited and the caret in it, or null when there is no caret in a note
// being edited (a selection is not a caret).
function caretInEditedNote() {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const node = range.startContainer;
    const element = node instanceof Element ? node : node.parentElement;
    if (element === null) return null;
    const content = element.closest(EDITED_CONTENT_SELECTOR);
    if (content === null) return null;
    return { content, node, offset: range.startOffset };
}

// Text selected in the note being edited, as before typing over it: the preview stays as it was.
function isSelectingInEditedNote() {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || selection.isCollapsed) return false;
    const node = selection.anchorNode;
    const element = node instanceof Element ? node : node.parentElement;
    return element !== null && element.closest(EDITED_CONTENT_SELECTOR) !== null;
}

function childIndex(node) {
    return Array.prototype.indexOf.call(node.parentNode.childNodes, node);
}

// The note's content as it would be saved, with CARET_MARK where the caret is. The
// mark goes into a copy: the note's text is never changed.
function markedContentHtml(caret) {
    const path = [];
    for (let node = caret.node; node !== caret.content; node = node.parentNode) path.unshift(childIndex(node));
    const copy = caret.content.cloneNode(true);
    let target = copy;
    for (const index of path) target = target.childNodes[index];
    if (target instanceof Text) {
        target.insertData(caret.offset, CARET_MARK);
    } else if (caret.offset === target.childNodes.length) {
        target.appendChild(document.createTextNode(CARET_MARK));
    } else {
        target.insertBefore(document.createTextNode(CARET_MARK), target.childNodes[caret.offset]);
    }
    return sanitizeNoteHtmlForStorage(copy.innerHTML);
}

function clearTimer(field) {
    if (moduleState[field] === null) return;
    clearTimeout(moduleState[field]);
    setState(field, null);
}

function hidePanel() {
    clearTimer('brokenTimer');
    if (moduleState.panel === null) return;
    moduleState.panel.remove();
    setState('panel', null);
}

// The caret left every formula: the next one starts fresh.
function forgetFormula() {
    hidePanel();
    setState('askedContent', null);
    setState('lastGood', null);
    setState('isDismissed', false);
}

function caretRect(caret) {
    const range = document.createRange();
    range.setStart(caret.node, caret.offset);
    range.collapse(true);
    const rects = range.getClientRects();
    if (rects.length > 0) return rects[rects.length - 1];
    if (caret.node instanceof Text && caret.offset > 0) {
        range.setStart(caret.node, caret.offset - 1);
        return range.getBoundingClientRect();
    }
    const box = (caret.node instanceof Element ? caret.node : caret.node.parentElement).getBoundingClientRect();
    return { left: box.left, top: box.top, bottom: box.bottom };
}

// Just below the caret's line, its left edge at the caret: it follows the caret as the user types.
function placePanel(caret) {
    const panel = moduleState.panel;
    const line = caretRect(caret);
    const { left, top } = placePasteFormatOffer({
        anchor: { left: line.left, top: line.top, bottom: line.bottom },
        // Its exact size: a whole-pixel height would put it a fraction off the line above it.
        width: panel.getBoundingClientRect().width, height: panel.getBoundingClientRect().height,
        viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
    });
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
}

// Full strength at once, or fading toward the ghost.
function setStrength(isFaded) {
    const panel = moduleState.panel;
    if (isFaded) {
        panel.style.transition = `opacity ${FADE_MS}ms ease-out`;
        panel.style.opacity = String(GHOST_OPACITY);
        return;
    }
    panel.style.transition = 'none';
    panel.style.opacity = String(FULL_OPACITY);
}

// The table scrolled inside the panel so the caret's row is in the middle, as far as it can be.
function showCaretRow(caretRow) {
    const panel = moduleState.panel;
    const rows = panel.querySelectorAll('tbody > tr');
    if (caretRow === NO_CARET_ROW || caretRow >= rows.length) return;
    const panelBox = panel.getBoundingClientRect();
    const rowBox = rows[caretRow].getBoundingClientRect();
    const rowTopInPanel = rowBox.top - panelBox.top + panel.scrollTop;
    panel.scrollTop = rowTopInPanel - half(panel.clientHeight - rowBox.height);
}

// Width in pixels of what is around an element's content: its padding and border on two sides.
function chrome(style, firstSide, secondSide) {
    return ['padding', 'border'].reduce((sum, part) => {
        const suffix = part === 'border' ? 'Width' : '';
        return sum + Number.parseFloat(style[`${part}${firstSide}${suffix}`]) + Number.parseFloat(style[`${part}${secondSide}${suffix}`]);
    }, 0);
}

// A diagram scaled down to fit the panel's room, keeping its proportions; never scaled up.
function fitDiagram() {
    const panel = moduleState.panel;
    const svg = panel.querySelector('svg');
    if (svg === null || svg.viewBox.baseVal === null || svg.viewBox.baseVal.width === 0) return;
    const style = window.getComputedStyle(panel);
    const roomWidth = window.innerWidth - VIEWPORT_MARGIN_PX - VIEWPORT_MARGIN_PX - chrome(style, 'Left', 'Right');
    const roomHeight = window.innerHeight * PANEL_HEIGHT_SHARE - chrome(style, 'Top', 'Bottom');
    const { width, height } = svg.viewBox.baseVal;
    const scale = Math.min(NO_SCALE_UP, roomWidth / width, roomHeight / height);
    svg.style.maxWidth = 'none';
    svg.setAttribute('width', String(width * scale));
    svg.setAttribute('height', String(height * scale));
}

function showPanel({ caret, kind, html, error, caretRow, isFaded }) {
    if (moduleState.panel === null) {
        const panel = document.createElement('div');
        panel.className = 'edit-preview';
        panel.setAttribute('aria-hidden', 'true');
        panel.style.left = '0px';
        panel.style.top = '0px';
        document.body.appendChild(panel);
        setState('panel', panel);
    }
    const panel = moduleState.panel;
    panel.classList.toggle('edit-preview-has-error', error !== '');
    panel.classList.toggle(WIDE_CLASS, WIDE_KINDS.has(kind) && error === '');
    if (error !== '') {
        panel.style.fontSize = '';
        panel.textContent = error;
    } else if (kind === PREVIEW_MERMAID) {
        panel.style.fontSize = '';
        panel.innerHTML = mermaidPreviewHtml(html);
        fitDiagram();
    } else {
        // Drawn at the note's size, as the note will draw it.
        panel.style.fontSize = window.getComputedStyle(caret.content).fontSize;
        panel.innerHTML = serverRenderedHtml(html);
    }
    placePanel(caret);
    panel.scrollTop = 0;
    if (error === '') showCaretRow(caretRow);
    setStrength(isFaded);
}

function showAnswer(caret, preview) {
    if (preview.kind === PREVIEW_NONE) {
        forgetFormula();
        return;
    }
    if (moduleState.isDismissed) return;
    const { kind, html, error, caretRow } = preview;
    // The caret went from a formula into a table (or back) without leaving both: nothing carries over.
    if (moduleState.lastGood !== null && moduleState.lastGood.kind !== kind) setState('lastGood', null);
    const isGood = error === '' && !preview.hasUnknownCommand;
    if (isGood) {
        setState('lastGood', { kind, html, caretRow });
        showPanel({ caret, kind, html, error: '', caretRow, isFaded: false });
        return;
    }
    const lastGood = moduleState.lastGood;
    if (lastGood === null) {
        hidePanel();
    } else {
        showPanel({ caret, kind, html: lastGood.html, error: '', caretRow: lastGood.caretRow, isFaded: true });
    }
    // Still broken after a pause: why, or the drawing with the command it does not know, as the note shows it.
    setState('brokenTimer', setTimeout(() => {
        setState('brokenTimer', null);
        showPanel({ caret, kind, html, error, caretRow, isFaded: false });
    }, BROKEN_PAUSE_MS));
}

// A diagram is drawn in the browser, as the note's are, once typing has paused a little longer.
function drawDiagramLater(caret, source, serial) {
    setState('drawTimer', setTimeout(async () => {
        setState('drawTimer', null);
        const drawn = await drawMermaidPreview(source);
        if (serial !== moduleState.requestSerial || isSelectingInEditedNote()) return;
        let error = '';
        if (!drawn.isValid) error = INVALID_DIAGRAM;
        showAnswer(caret, { kind: PREVIEW_MERMAID, html: drawn.svg, error, hasUnknownCommand: false, caretRow: NO_CARET_ROW });
    }, DIAGRAM_PAUSE_MS - TYPING_PAUSE_MS));
}

async function askForPreview() {
    setState('typingTimer', null);
    if (isSelectingInEditedNote()) return;
    const caret = caretInEditedNote();
    if (!isEnabled() || caret === null || caret.content.textContent.includes(CARET_MARK)) {
        forgetFormula();
        return;
    }
    // Leaving a note can redraw it without moving the selection: nothing of its formula carries over.
    if (caret.content !== moduleState.askedContent) forgetFormula();
    setState('askedContent', caret.content);
    const noteElement = caret.content.closest('.note');
    setState('requestSerial', moduleState.requestSerial + 1);
    const serial = moduleState.requestSerial;
    const preview = await NotesAPI.fetchEditPreview(markedContentHtml(caret), getTagBarValue(noteElement));
    if (serial !== moduleState.requestSerial || isSelectingInEditedNote()) return;
    if (!caret.content.isConnected || caretInEditedNote() === null) {
        forgetFormula();
        return;
    }
    if (preview.kind === PREVIEW_MERMAID && !moduleState.isDismissed) {
        drawDiagramLater(caret, preview.diagramSource, serial);
        return;
    }
    showAnswer(caret, preview);
}

// A key or a caret move: ask again once typing pauses. Until then a broken formula shows no reason.
function scheduleAsk() {
    clearTimer('typingTimer');
    clearTimer('brokenTimer');
    clearTimer('drawTimer');
    setState('requestSerial', moduleState.requestSerial + 1);
    // A failed request is not swallowed: it reaches the error overlay, as for the `[[` list.
    setState('typingTimer', setTimeout(async () => {
        await askForPreview();
    }, TYPING_PAUSE_MS));
}

// The page or a list scrolled: the panel hides until the next key or caret move. Its own
// scrolling, to the caret's row, is not one.
function handleScroll(event) {
    if (moduleState.panel !== null && event.target instanceof Node && moduleState.panel.contains(event.target)) return;
    hidePanel();
}

// Escape hides only the panel; editing goes on.
function handleKeyDown(event) {
    if (event.key !== 'Escape' || moduleState.panel === null) return;
    event.preventDefault();
    event.stopPropagation();
    setState('isDismissed', true);
    hidePanel();
}

export function initializeEditPreviews() {
    if (moduleState.initialized) return;
    setState('initialized', true);
    document.addEventListener('selectionchange', unlessDiagramEditorOpen(scheduleAsk));
    // Typing that leaves the caret where it was (Delete) changes the formula too.
    document.addEventListener('input', unlessDiagramEditorOpen(scheduleAsk), { capture: true });
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    document.addEventListener('scroll', handleScroll, { capture: true, passive: true });
    window.addEventListener('resize', hidePanel);
}
