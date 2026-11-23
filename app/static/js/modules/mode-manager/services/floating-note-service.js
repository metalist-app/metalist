import { watchFoldArrows } from './fold-arrow-alignment-service.js';
import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { NotesAPI } from '../../api-client.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';
import { CommandGate } from './command-gate-service.js';
import { createFloatingNoteElements, applyFloatingNoteRect, getFloatingNoteTitle } from './floating-note-dom.js';
import { constrainFloatingNoteRect, moveFloatingNoteRect } from './floating-note-layout.js';
import { ensureAnchorsOpenInNewTabs } from './link-target-service.js';
import { downloadFileReference } from './file-reference-service.js';
import { openFileViewer, opensInViewer } from './file-viewer-service.js';
import { playMediaFile } from './media-player-service.js';
import { handleValueButtonClick } from './value-buttons-service.js';
import { beginMoveDragInWindow, continueMoveDragInWindow, finishMoveDragInWindow, takeClickAfterMoveDrag } from '../events/mouse-events.js';
import { copyTextToClipboard, normalizeCopyableText } from '../events/mouse-events.js';
import { editedWindowHost, findNoteContentElement, recordPress } from '../../editing-surface.js';
import { drawWindowNotes, editNoteInWindow } from './floating-note-editing.js';
import { captureClickAnchor } from './viewport-hold-service.js';
import { watchFoldability } from './collapse-affordance-service.js';
import { collapseNote, expandNote } from '../actions/note-actions.js';
import { galleryElementOf, galleryNoteIdOf, toggleGalleryOutline } from './gallery-view-service.js';
import { actionDeselectNote } from '../actions/selection-actions.js';

const moduleState = ApplicationState.createFields('floating-note-service', {
    windows: Object.create(null),
    order: [],
    timer: null,
    refreshing: false,
    gesture: null,
    listening: false,
});
const ISOLATED_EVENTS = Object.freeze([
    'pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'mousedown', 'mouseup',
    'mousemove', 'mouseover', 'mouseout', 'click', 'dblclick', 'contextmenu',
    'keydown', 'keyup', 'keypress', 'beforeinput', 'input', 'paste', 'cut', 'copy', 'dragstart',
]);
// Floating notes stack from this z-index upward, frontmost last.
const FLOATING_NOTE_BASE_Z_INDEX = 2500;
const FLOATING_NOTE_REFRESH_INTERVAL_MS = 500;
// A new window opens below and to the right of the previous one; after this many the cascade starts over.
const CASCADE_POSITIONS = 8;
const CASCADE_STEP_PX = 28;
const FIRST_WINDOW_LEFT_PX = 80;
const FIRST_WINDOW_TOP_PX = 90;
const NEW_WINDOW_WIDTH_PX = 460;
const NEW_WINDOW_HEIGHT_PX = 380;
const RESIZE_KEY_STEP_PX = 20;
// MouseEvent.button of the right button.
const SECONDARY_MOUSE_BUTTON = 2;

function viewport() {
    return {width: window.innerWidth, height: window.innerHeight};
}

function bringToFront(id) {
    if (moduleState.order.at(-1) === id) return;
    moduleState.order = [...moduleState.order.filter(existing => existing !== id), id];
    moduleState.order.forEach((windowId, index) => {
        moduleState.windows[windowId].element.style.zIndex = String(FLOATING_NOTE_BASE_Z_INDEX + index);
    });
}

function setRect(entry, rect) {
    if (stateValuesEqual(entry.rect, rect)) return;
    entry.rect = rect;
    applyFloatingNoteRect(entry.element, rect);
}

function finishGesture() {
    if (moduleState.gesture === null) return;
    const {id, pointerId} = moduleState.gesture;
    moduleState.gesture = null;
    const entry = moduleState.windows[id];
    if (entry && entry.element.hasPointerCapture(pointerId)) entry.element.releasePointerCapture(pointerId);
}

export function closeFloatingNote(id) {
    if (!Object.hasOwn(moduleState.windows, id)) return;
    if (moduleState.gesture?.id === id) finishGesture();
    moduleState.windows[id].element.remove();
    delete moduleState.windows[id];
    moduleState.order = moduleState.order.filter(existing => existing !== id);
    if (moduleState.order.length === 0) {
        window.clearInterval(moduleState.timer);
        moduleState.timer = null;
        window.removeEventListener('pointerdown', recordPress, { capture: true });
        for (const type of ISOLATED_EVENTS) window.removeEventListener(type, handleWindowEvent, { capture: true });
        window.removeEventListener('resize', fitWindows);
        window.removeEventListener('blur', finishGesture);
        moduleState.listening = false;
    }
}

export function closeAllFloatingNotes() {
    for (const id of [...moduleState.order]) closeFloatingNote(id);
}

function fitWindows() {
    for (const entry of Object.values(moduleState.windows)) {
        setRect(entry, constrainFloatingNoteRect(entry.rect, viewport()));
    }
}

function startWindowEvents() {
    if (moduleState.listening) return;
    // Before the windows' own handlers, which stop presses in them reaching the page.
    window.addEventListener('pointerdown', recordPress, { capture: true });
    for (const type of ISOLATED_EVENTS) window.addEventListener(type, handleWindowEvent, { capture: true });
    window.addEventListener('resize', fitWindows);
    window.addEventListener('blur', finishGesture);
    moduleState.listening = true;
    moduleState.timer = window.setInterval(() => { void refreshFloatingNotes(); }, FLOATING_NOTE_REFRESH_INTERVAL_MS);
}

export async function openFloatingNote(noteId) {
    if (typeof noteId !== 'string' || noteId.length === 0) throw new Error('Floating note requires noteId');
    const mainApp = document.getElementById('main-app');
    if (!(mainApp instanceof HTMLElement)) throw new Error('Floating note requires main app');
    const id = crypto.randomUUID();
    const elements = createFloatingNoteElements(id);
    const offset = (moduleState.order.length % CASCADE_POSITIONS) * CASCADE_STEP_PX;
    const rect = constrainFloatingNoteRect({x: FIRST_WINDOW_LEFT_PX + offset, y: FIRST_WINDOW_TOP_PX + offset, width: NEW_WINDOW_WIDTH_PX, height: NEW_WINDOW_HEIGHT_PX}, viewport());
    moduleState.windows[id] = {...elements, noteId, rect, revision: '', markup: ''};
    applyFloatingNoteRect(elements.element, rect);
    mainApp.appendChild(elements.element);
    watchFoldArrows(elements.tree);
    watchFoldability(elements.tree);
    bringToFront(id);
    startWindowEvents();
    elements.element.focus({preventScroll: true});
    await refreshWindow(id);
    return id;
}

function validateSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== 'object'
        || typeof snapshot.revision !== 'string' || snapshot.revision.length === 0
        || !Array.isArray(snapshot.structure) || snapshot.notes === null || typeof snapshot.notes !== 'object'
        || !['ready', 'unchanged', 'deleted'].includes(snapshot.status)) {
        throw new Error('Invalid floating note response');
    }
    if ((snapshot.status === 'ready') !== (snapshot.structure.length > 0)) {
        throw new Error('Floating note notes do not match response status');
    }
}

// What the window draws, to tell a new answer that draws the same apart: each note's version.
function drawingOf(snapshot) {
    return snapshot.structure.map(entry => `${entry.id}:${entry.hash}`).join(' ');
}

async function refreshWindow(id) {
    const entry = moduleState.windows[id];
    if (!entry) return;
    // A note in it is edited: it shows that, until editing leaves it (case 6).
    if (editedWindowHost() === entry.element) return;
    const snapshot = await NotesAPI.getFloatingNote(entry.noteId, entry.revision).catch(error => {
        rethrowUnexpectedError(error);
        if (Object.hasOwn(moduleState.windows, id)) entry.status.textContent = 'Unable to refresh. Retrying…';
        return null;
    });
    // Closing/logging out during a request must never republish its content.
    if (snapshot === null || !Object.hasOwn(moduleState.windows, id)) return;
    validateSnapshot(snapshot);
    if (entry.revision !== snapshot.revision) entry.revision = snapshot.revision;
    entry.status.textContent = snapshot.status === 'deleted' ? 'This note was deleted.' : '';
    if (snapshot.status === 'deleted') {
        entry.title.textContent = 'Deleted note';
    }
    if (snapshot.status === 'unchanged' || entry.markup === drawingOf(snapshot)) return;
    entry.markup = drawingOf(snapshot);
    const scrollTop = entry.scroll.scrollTop;
    entry.tree.replaceChildren();
    // As the list draws the notes: folded as saved, galleries as their grid (agreed 2026-11-22).
    if (snapshot.status === 'ready') drawWindowNotes(entry.tree, snapshot.structure, snapshot.notes, null);
    entry.scroll.scrollTop = scrollTop;
    if (snapshot.status === 'ready') {
        entry.title.textContent = getFloatingNoteTitle(entry.tree);
    }
    for (const control of entry.tree.querySelectorAll('.meta-status-toggle, .meta-markdown-task-toggle, .note-shell-run, input, textarea, select')) {
        control.setAttribute('disabled', '');
    }
    ensureAnchorsOpenInNewTabs(entry.tree);
}

export async function refreshFloatingNotes() {
    // Hidden tabs skip refreshes; the next visible tick catches up.
    if (document.hidden) return;
    if (moduleState.refreshing || CommandGate.isTurnTaken() || moduleState.order.length === 0) return;
    moduleState.refreshing = true;
    // In a turn: a command (a drag in a window, a note edited there) runs after the windows are drawn.
    await CommandGate.runBackground('floatingNotes.refresh', () => Promise.all([...moduleState.order].map(refreshWindow))).finally(() => {
        moduleState.refreshing = false;
    });
}

function handleWindowClick(event, target, id) {
    if (target.closest('.floating-note-close')) {
        event.preventDefault();
        // A note edited in it is saved and left first.
        if (editedWindowHost() === moduleState.windows[id].element) {
            void CommandGate.run('floatingNote.close', async () => {
                await actionDeselectNote();
                closeFloatingNote(id);
            });
            return;
        }
        closeFloatingNote(id);
        return;
    }
    if (handleValueButtonClick(event, target)) return;
    // A fold arrow folds or unfolds the note everywhere, the list too (agreed 2026-11-22).
    const fold = target.closest('.note-collapse-toggle');
    if (fold !== null) {
        event.preventDefault();
        const folded = fold.closest('.note[data-note-id]');
        const noteId = folded.dataset.noteId;
        if (folded.classList.contains('collapsed')) {
            void CommandGate.run('floatingNote.expand', () => expandNote(noteId));
        } else {
            void CommandGate.run('floatingNote.collapse', () => collapseNote(noteId));
        }
        return;
    }
    // A gallery's switch between its grid and its notes: the same choice as in the list.
    const gallerySwitch = target.closest('.meta-gallery-switch');
    if (gallerySwitch !== null) {
        event.preventDefault();
        const galleryNoteId = galleryNoteIdOf(galleryElementOf(gallerySwitch));
        void CommandGate.run('floatingNote.gallerySwitch', () => toggleGalleryOutline(galleryNoteId));
        return;
    }
    const credential = target.closest('.meta-credential-value');
    const copyable = target.closest('.meta-copyable');
    if (credential) {
        event.preventDefault();
        void copyTextToClipboard(credential.dataset.copyValue, credential, 'meta-credential-copied');
        return;
    }
    if (copyable && !target.closest('a') && window.getSelection()?.isCollapsed) {
        event.preventDefault();
        const value = typeof copyable.dataset.copyValue === 'string' ? copyable.dataset.copyValue : copyable.textContent;
        void copyTextToClipboard(normalizeCopyableText(value), copyable, 'meta-copyable-copied');
        return;
    }
    const reference = target.closest('.note-reference-link');
    if (reference) {
        event.preventDefault();
        const container = reference.closest('[data-ref-note-id]');
        if (!container) throw new Error('Floating reference missing target');
        void CommandGate.run('floatingNote.reference', () => openFloatingNote(container.dataset.refNoteId));
        return;
    }
    const play = target.closest('.note-file-media-play');
    if (play) {
        event.preventDefault();
        void CommandGate.run('floatingNote.play', () => playMediaFile(play));
        return;
    }
    // As in the list: Open (or a link to a file the viewer shows) opens it, Download downloads it.
    const file = target.closest('button.note-file-reference-link, .note-file-action');
    if (file) {
        event.preventDefault();
        if (opensInViewer(file)) {
            void CommandGate.run('floatingNote.open', () => openFileViewer(file.dataset.fileRefId));
            return;
        }
        void CommandGate.run('floatingNote.download', () => downloadFileReference(file.dataset.fileRefId));
        return;
    }
    // A click in a note's text edits it there (case 1).
    const content = target.closest('.note-content');
    if (content !== null && !target.closest('a, button, input, select, textarea')) {
        event.preventDefault();
        const note = content.closest('.note[data-note-id]');
        // Where clicked, as the list keeps it: the caret lands on the same text in the note's source.
        const anchor = captureClickAnchor(note, event.clientX, event.clientY);
        void CommandGate.run('floatingNote.edit', () => editNoteInWindow(windowToEdit(id), note.dataset.noteId, anchor));
    }
}

// A right-click on a note of the window's drawing (the maintainer, 2026-11-22: "I can't
// right-click on a note not in editing mode inside of the floating window to delete it or do
// other things"). The note menu works on a note the editor can find, which a window's drawing
// is not until one of its notes is edited: so the note is edited there first, where right-clicked,
// then its menu opens at the same spot, the note's own, as a right-click on it while edited.
function openNoteMenuInWindow(event, target, id) {
    const content = target.closest('.note-content');
    if (content === null || !moduleState.windows[id].tree.contains(content)) return;
    event.preventDefault();
    const note = content.closest('.note[data-note-id]');
    const noteId = note.dataset.noteId;
    const anchor = captureClickAnchor(note, event.clientX, event.clientY);
    const where = { clientX: event.clientX, clientY: event.clientY };
    void CommandGate.run('floatingNote.menu', () => editNoteInWindow(windowToEdit(id), noteId, anchor)).then(() => {
        const edited = findNoteContentElement(noteId);
        // Not edited after all (another view holds it, or it left the window): no menu.
        if (edited === null || !edited.isContentEditable) return;
        edited.dispatchEvent(new MouseEvent('contextmenu', {
            bubbles: true, cancelable: true, composed: true, button: SECONDARY_MOUSE_BUTTON, ...where,
        }));
    });
}

// A window as floating-note-editing.js edits in it.
function windowToEdit(id) {
    const entry = moduleState.windows[id];
    return {
        id, noteId: entry.noteId, element: entry.element, tree: entry.tree,
        // Drawn again from the server once editing leaves it.
        showNotes: () => {
            if (!Object.hasOwn(moduleState.windows, id)) return;
            if (entry.revision !== '') entry.revision = '';
            if (entry.markup !== '') entry.markup = '';
            void refreshWindow(id);
        },
    };
}

function handleWindowEvent(event) {
    const path = event.composedPath();
    const host = path.find(node => node instanceof HTMLElement && node.classList.contains('floating-note-window'));
    if (!host) return;
    const id = host.dataset.floatingNoteId;
    const entry = moduleState.windows[id];
    if (!entry) return;
    // The notes of a window a note is edited in are the editor's: their events go on to it.
    if (editedWindowHost() === host && path.some(node => node instanceof HTMLElement && node.classList.contains('floating-note-editing-tree'))) {
        if (event.type === 'pointerdown') bringToFront(id);
        return;
    }
    // Stop main-editor delegates at the window capture phase. Native selection,
    // copying, scrolling and external-link activation retain their defaults.
    event.stopPropagation();
    const target = path.find(node => node instanceof Element);
    if (!target) return;
    if (event.type === 'pointerdown') {
        bringToFront(id);
        if (event.button !== 0 || target.closest('.floating-note-close')) return;
        const kind = target.closest('.floating-note-resize') ? 'resize' : 'move';
        if (kind === 'move' && !target.closest('.floating-note-header')) return;
        finishGesture();
        moduleState.gesture = {id, pointerId: event.pointerId, kind, x: event.clientX, y: event.clientY, rect: {...entry.rect}};
        host.setPointerCapture(event.pointerId);
        host.focus({preventScroll: true});
        event.preventDefault();
    } else if (event.type === 'mousedown') {
        // A press on a note of the window's drawing may start dragging it (mouse-events.js).
        if (path.includes(entry.tree)) {
            beginMoveDragInWindow(event, target, { tree: entry.tree, scrollArea: entry.scroll });
        }
    } else if (event.type === 'mousemove') {
        continueMoveDragInWindow(event, target);
    } else if (event.type === 'mouseup') {
        finishMoveDragInWindow(event, target);
    } else if (event.type === 'pointermove' && moduleState.gesture?.pointerId === event.pointerId) {
        setRect(entry, moveFloatingNoteRect(moduleState.gesture, event.clientX, event.clientY, viewport()));
    } else if (event.type === 'pointerup' || event.type === 'pointercancel') {
        finishGesture();
    } else if (event.type === 'click') {
        // The click that ends a drag is no click on the note.
        if (takeClickAfterMoveDrag()) {
            event.preventDefault();
            return;
        }
        handleWindowClick(event, target, id);
    } else if (event.type === 'contextmenu') {
        openNoteMenuInWindow(event, target, id);
    } else if (event.type === 'keydown') {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeFloatingNote(id);
        } else if (target.closest('.floating-note-resize') && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault();
            const width = entry.rect.width + (event.key === 'ArrowRight' ? RESIZE_KEY_STEP_PX : event.key === 'ArrowLeft' ? -RESIZE_KEY_STEP_PX : 0);
            const height = entry.rect.height + (event.key === 'ArrowDown' ? RESIZE_KEY_STEP_PX : event.key === 'ArrowUp' ? -RESIZE_KEY_STEP_PX : 0);
            setRect(entry, constrainFloatingNoteRect({...entry.rect, width, height}, viewport()));
        }
    } else if (['beforeinput', 'paste', 'cut', 'dragstart'].includes(event.type)) {
        event.preventDefault();
    }
}
