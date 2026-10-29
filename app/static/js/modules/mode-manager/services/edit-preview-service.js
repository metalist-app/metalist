import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { sanitizeNoteHtmlForStorage } from '../../note-html-sanitizer.js';
import { serverRenderedHtml } from '../../server-rendered-html.js';
import { unlessDiagramEditorOpen } from '../../excalidraw/excalidraw-editor-state.js';
import { getTagBarValue } from './tag-bar-service.js';
import { placePasteFormatOffer } from './paste-format-offer-service.js';

// Previews while editing (docs/ui/content-formatting.md, "Previews while editing";
// agreed 2026-10-29). With the caret inside a formula of the note being edited, a
// small panel just below that line, under the caret, shows the formula drawn. The server finds the
// formula under the caret and draws it as the note draws it (app/services/edit_previews.py),
// so a preview never disagrees with the note. The panel floats: the note's text
// never moves. While the formula is broken mid-typing the last good drawing fades
// toward a ghost; a pause shows why it is broken. Escape hides it until the caret
// next enters a formula; scrolling hides it until the next key or caret move.
// "Previews While Editing" turns it off; the phone has none.

// A Unicode noncharacter marks the caret; the server looks for the same one.
const CARET_MARK = '\ufdd0';
const EDITED_CONTENT_SELECTOR = '.note.editing > .note-content';
const PREVIEWS_ON_CLASS = 'pref-edit-previews';
const PHONE_CLASS = 'phone-layout';
const PREVIEW_NONE = 'none';

// Tuning (the maintainer wants to try these before settling them):
// the preview asks once typing pauses this long,
const TYPING_PAUSE_MS = 150;
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
    // The note content the caret was last asked about: a caret in another note starts fresh.
    askedContent: null,
    // The formula under the caret drawn when it last rendered, while the caret stays in it.
    lastGoodHtml: null,
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
    setState('lastGoodHtml', null);
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
        width: panel.offsetWidth, height: panel.offsetHeight,
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

function showPanel({ caret, html, error, isFaded }) {
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
    if (error !== '') {
        panel.style.fontSize = '';
        panel.textContent = error;
    } else {
        // Drawn at the note's size, as the note will draw it.
        panel.style.fontSize = window.getComputedStyle(caret.content).fontSize;
        panel.innerHTML = serverRenderedHtml(html);
    }
    placePanel(caret);
    setStrength(isFaded);
}

function showAnswer(caret, preview) {
    if (preview.kind === PREVIEW_NONE) {
        forgetFormula();
        return;
    }
    if (moduleState.isDismissed) return;
    const isGood = preview.error === '' && !preview.hasUnknownCommand;
    if (isGood) {
        setState('lastGoodHtml', preview.html);
        showPanel({ caret, html: preview.html, error: '', isFaded: false });
        return;
    }
    if (moduleState.lastGoodHtml === null) {
        hidePanel();
    } else {
        showPanel({ caret, html: moduleState.lastGoodHtml, error: '', isFaded: true });
    }
    // Still broken after a pause: why, or the drawing with the command it does not know, as the note shows it.
    setState('brokenTimer', setTimeout(() => {
        setState('brokenTimer', null);
        showPanel({ caret, html: preview.html, error: preview.error, isFaded: false });
    }, BROKEN_PAUSE_MS));
}

async function askForPreview() {
    setState('typingTimer', null);
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
    if (serial !== moduleState.requestSerial) return;
    if (!caret.content.isConnected || caretInEditedNote() === null) {
        forgetFormula();
        return;
    }
    showAnswer(caret, preview);
}

// A key or a caret move: ask again once typing pauses. Until then a broken formula shows no reason.
function scheduleAsk() {
    clearTimer('typingTimer');
    clearTimer('brokenTimer');
    setState('requestSerial', moduleState.requestSerial + 1);
    // A failed request is not swallowed: it reaches the error overlay, as for the `[[` list.
    setState('typingTimer', setTimeout(async () => {
        await askForPreview();
    }, TYPING_PAUSE_MS));
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
    document.addEventListener('scroll', hidePanel, { capture: true, passive: true });
    window.addEventListener('resize', hidePanel);
}
