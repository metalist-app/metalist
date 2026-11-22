import { ApplicationState } from './application-state.js';

// Where the note being edited lives (docs/ui/state-handling.md, "Floating note windows"): the
// list, or the tree of a floating window a note is edited in. The editor finds notes here, so
// the same code edits a note in either; the list's own renderer looks in the list alone
// (differential-view-service.js). A window's notes are in its shadow root while nothing in it is
// edited, where no page lookup sees them, and in the page (slotted into the window) while one is.

const moduleState = ApplicationState.createFields('editing-surface', {
    // The floating window's tree holding the edited note, or null while editing in the list.
    windowTree: null,
    // That window's element, and what leaves its editing and switches it to another of its notes
    // (floating-note-editing.js): the selection actions call them without importing the window.
    windowHost: null,
    // The note the window shows (its top note), which no new note may be put beside: it would be
    // outside the window (the maintainer, 2026-11-22).
    windowNoteId: null,
    leaveWindow: null,
    switchInWindow: null,
    followWindow: null,
    // Whether the last press was in the window being edited: a note switched to after it is
    // edited there, after a press anywhere else in the list.
    isLastPressInWindow: false,
});

/** The element the editor looks for notes in: the edited window's tree, or the whole page. */
export function noteLookupRoot() {
    if (moduleState.windowTree !== null) return moduleState.windowTree;
    return document;
}

/** The note's element where editing happens, or null when it is not there. */
export function findNoteElement(noteId) {
    if (typeof noteId !== 'string' || noteId === '') throw new Error('findNoteElement requires a note id');
    return noteLookupRoot().querySelector(`.note[data-note-id="${noteId}"]`);
}

/** The note's element in the list itself, or null when the list does not show it. */
export function findListNoteElement(noteId) {
    if (typeof noteId !== 'string' || noteId === '') throw new Error('findListNoteElement requires a note id');
    const list = document.getElementById('notes-container');
    if (list === null) return null;
    return list.querySelector(`.note[data-note-id="${noteId}"]`);
}

export function isEditingInWindow() {
    return moduleState.windowTree !== null;
}

/** Whether `noteId` is the note shown by the window a note is edited in: no note goes beside it there. */
export function isEditedWindowsOwnNote(noteId) {
    return moduleState.windowNoteId !== null && moduleState.windowNoteId === noteId;
}

/** The window element a note is edited in, or null. */
export function editedWindowHost() {
    return moduleState.windowHost;
}

/** The scrolling area of the window a note is edited in (floating-note-dom.js). */
export function editedWindowScrollArea() {
    if (moduleState.windowHost === null) throw new Error('No note is edited in a floating window');
    const area = moduleState.windowHost.shadowRoot.querySelector('.floating-note-scroll');
    if (area === null) throw new Error('A floating window has its scrolling area');
    return area;
}

/**
 * A note is now edited in a floating window: `tree` holds the window's notes, `host` is the
 * window, `leave()` takes the window out of editing (after the note is saved and left) and
 * `switchTo(noteId, clickAnchor)` edits another of its notes there.
 */
export function startEditingInWindow({ tree, host, windowNoteId, leave, switchTo, follow }) {
    if (!(tree instanceof HTMLElement) || !(host instanceof HTMLElement) || !host.contains(tree)) {
        throw new Error('startEditingInWindow requires the window and its tree of notes');
    }
    if (typeof windowNoteId !== 'string' || windowNoteId === '') {
        throw new Error('startEditingInWindow requires the note the window shows');
    }
    if (typeof leave !== 'function' || typeof switchTo !== 'function' || typeof follow !== 'function') {
        throw new Error('startEditingInWindow requires how to leave, switch and follow');
    }
    if (moduleState.windowTree !== null) throw new Error('A note is already edited in a floating window');
    moduleState.windowTree = tree;
    moduleState.windowHost = host;
    moduleState.windowNoteId = windowNoteId;
    moduleState.leaveWindow = leave;
    moduleState.switchInWindow = switchTo;
    moduleState.followWindow = follow;
    if (!moduleState.isLastPressInWindow) moduleState.isLastPressInWindow = true;
}

/** Editing has left the window (the note saved and left): the window shows its notes again. */
export function leaveEditingWindow() {
    if (moduleState.windowTree === null) return;
    const leave = moduleState.leaveWindow;
    moduleState.windowTree = null;
    moduleState.windowHost = null;
    moduleState.windowNoteId = null;
    moduleState.leaveWindow = null;
    moduleState.switchInWindow = null;
    moduleState.followWindow = null;
    leave();
}

/**
 * Editing moves to `noteId` (a click, a key, a new note): true when the window being edited
 * takes it, the user working in the window and the note being one of its own (a new note made
 * there is); false when the caller edits it in the list, having left the window first.
 */
export async function switchesInWindow(noteId, clickAnchor) {
    if (moduleState.windowTree === null || !moduleState.isLastPressInWindow) return false;
    const isTaken = await moduleState.switchInWindow(noteId, clickAnchor);
    if (typeof isTaken !== 'boolean') throw new Error('A floating window answers whether it edits the note');
    return isTaken;
}

/** The list was drawn again while a note is edited in a window: the window follows its notes. */
export function noticeListRefreshedWhileEditingInWindow() {
    if (moduleState.windowTree === null) throw new Error('No note is edited in a floating window');
    moduleState.followWindow();
}

/** Every press, first: whether it is in the window being edited. */
export function recordPress(event) {
    if (moduleState.windowHost === null) return;
    const isInWindow = event.composedPath().includes(moduleState.windowHost);
    if (moduleState.isLastPressInWindow !== isInWindow) moduleState.isLastPressInWindow = isInWindow;
}

/** The note's own text element where editing happens, or null when the note is not there. */
export function findNoteContentElement(noteId) {
    const note = findNoteElement(noteId);
    if (note === null) return null;
    return note.querySelector(':scope > .note-content');
}

// The pencil on the list's copy of a note edited in a floating window (main.css, with the pencil
// of a note another view edits); a click in that copy moves the editing to the list.
const EDITED_IN_WINDOW_CLASS = 'note-edited-in-window';

/** Every view answer: the note this view edits in a window (or null) shows its pencil in the list. */
export function markNoteEditedInWindow(noteId) {
    if (noteId !== null && (typeof noteId !== 'string' || noteId === '')) {
        throw new Error('markNoteEditedInWindow requires a note id or null');
    }
    for (const marker of document.querySelectorAll(`#notes-container .note > .${EDITED_IN_WINDOW_CLASS}`)) {
        if (marker.parentElement.dataset.noteId !== noteId) marker.remove();
    }
    if (noteId === null) return;
    const note = findListNoteElement(noteId);
    if (note === null || note.querySelector(`:scope > .${EDITED_IN_WINDOW_CLASS}`) !== null) return;
    const marker = document.createElement('span');
    marker.className = EDITED_IN_WINDOW_CLASS;
    marker.title = 'Being edited in a floating window';
    marker.setAttribute('aria-label', marker.title);
    note.appendChild(marker);
}

/** Whether `noteElement` is a copy of the note edited in a floating window (the list's, with its pencil). */
export function isCopyOfNoteEditedInWindow(noteElement) {
    if (!(noteElement instanceof Element)) throw new Error('isCopyOfNoteEditedInWindow requires a note element');
    return moduleState.windowTree !== null && !moduleState.windowTree.contains(noteElement);
}
