// One editor per root note (multi-view editing step 4; docs/design/multi-view-editing.md,
// "Step 4's cases"). Every view answer lists the roots other views edit (lockedRoots, with where);
// each shows a pencil on its top-left corner whose tooltip says where (case 3). A click in such a
// root takes it over at once and then does what was clicked (decided 2026-11-15): a click in its
// text waits for the other view to save and leave, then edits there (cases 4 and 5); a change the
// server refused for it (its fold arrow, a checkbox, a move) takes it over and is sent again, and
// neither view holds it afterwards (case 6, api-client.js). The view a root is taken from saves its
// typing and leaves (leaveTakenOverEditing).
import { ApplicationState } from '../../application-state.js';
import { CONFIG } from '../../config.js';
import { ErrorHandler } from '../../error-handler.js';
import { HttpRequestError, rethrowUnexpectedError } from '../../expected-errors.js';
import { FloatingMessages } from '../../floating-messages.js';
import { buildSessionHeaders } from '../../session-auth.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { CommandGate } from './command-gate-service.js';
import { askOtherTabsToCheckNow } from '../../views-in-this-browser.js';

const MARKER_CLASS = 'note-edit-lock';
// A take-over asks this often until the other view has let go (the server answers ready within
// its handover time, edit_locks.py HANDOVER_SECONDS).
const TAKE_OVER_ASK_MS = 150;
// Why a root is taken over: the view it is taken from says "Editing moved" or "Editing ended".
const TAKEN_TO_EDIT = false;
const TAKEN_FOR_A_CHANGE = true;
const NOT_SAVED_KEY = 'edit-lock-not-saved';

const lockState = ApplicationState.createFields('edit-lock-service', {
    // Root id → where another view edits it ("on your phone", "in another tab", …).
    lockedRoots: {},
    // The root a click is taking over (waiting for the other view to let go), and the root being
    // entered once it has: a stale view answer still listing it as locked does not stop that.
    takingOverRootId: '',
    enteringRootId: '',
    isEditedRootMovedElsewhere: false,
    // Search context id → where another view types its search (case 10).
    searchLocks: {},
    hasTypedSearch: false,
});

function requireWhereByRoot(lockedRoots) {
    if (lockedRoots === null || typeof lockedRoots !== 'object' || Array.isArray(lockedRoots)) {
        throw new Error('lockedRoots must map root ids to where they are edited');
    }
    for (const [rootId, where] of Object.entries(lockedRoots)) {
        if (rootId === '' || typeof where !== 'string' || where === '') {
            throw new Error('lockedRoots must map root ids to where they are edited');
        }
    }
}

function rootIdOfNote(noteId) {
    const note = document.querySelector(`#notes-container .note[data-note-id="${CSS.escape(noteId)}"]`);
    if (note === null) {
        return '';
    }
    const root = note.closest('#notes-container > .note');
    if (root === null) {
        throw new Error(`Note ${noteId} is shown outside a root note`);
    }
    return root.dataset.noteId;
}

function markerOf(root) {
    return root.querySelector(`:scope > .${MARKER_CLASS}`);
}

function renderMarkers() {
    for (const root of document.querySelectorAll('#notes-container > .note[data-note-id]')) {
        const rootId = root.dataset.noteId;
        const marker = markerOf(root);
        if (!Object.hasOwn(lockState.lockedRoots, rootId)) {
            if (marker !== null) marker.remove();
            continue;
        }
        const tooltip = `Being edited ${lockState.lockedRoots[rootId]}`;
        if (marker !== null) {
            marker.title = tooltip;
            continue;
        }
        const added = document.createElement('span');
        added.className = MARKER_CLASS;
        added.title = tooltip;
        added.setAttribute('aria-label', tooltip);
        root.appendChild(added);
    }
}

// Every view answer: the roots other views edit, shown with markers.
export function recordLockedRoots(lockedRoots) {
    requireWhereByRoot(lockedRoots);
    if (JSON.stringify(lockedRoots) !== JSON.stringify(lockState.lockedRoots)) {
        lockState.lockedRoots = { ...lockedRoots };
    }
    renderMarkers();
}

// Every view answer while editing: another view moved the edited root, so leaving edit mode keeps
// the note at the window's top still rather than following the edited one (case 9).
export function recordEditedRootMovedElsewhere(isMoved) {
    if (typeof isMoved !== 'boolean') {
        throw new Error('editedRootMovedElsewhere must be true or false');
    }
    if (lockState.isEditedRootMovedElsewhere !== isMoved) {
        lockState.isEditedRootMovedElsewhere = isMoved;
    }
}

export function isEditedRootMovedElsewhere() {
    return lockState.isEditedRootMovedElsewhere;
}

// Editing a note in a root another view edits: the root is taken over and enter goes on once the
// other view has let go (cases 4 and 5). True when it was, so the caller does not edit now.
export function takeOverInsteadOfEditing(noteId, enter) {
    if (typeof enter !== 'function') {
        throw new Error('takeOverInsteadOfEditing requires what to do once the root is taken over');
    }
    const rootId = rootIdOfNote(noteId);
    if (rootId === '' || rootId === lockState.enteringRootId) {
        return false;
    }
    // A second click while the first waits: the first goes on.
    if (lockState.takingOverRootId !== '') {
        return true;
    }
    if (!Object.hasOwn(lockState.lockedRoots, rootId)) {
        return false;
    }
    startTakeOver(rootId, enter);
    return true;
}

// Edit mode just entered here was refused: another view took the root a moment before (the view
// answer said so). The marker shows; the edit goes on once the root is taken back.
export function takeOverRefusedEdit(rootId, where, enter) {
    if (typeof rootId !== 'string' || rootId === '' || typeof where !== 'string' || where === '' || typeof enter !== 'function') {
        throw new Error('takeOverRefusedEdit requires the root, where it is edited and what to do then');
    }
    recordRefusal(rootId, where);
    if (lockState.takingOverRootId !== '') {
        return;
    }
    startTakeOver(rootId, enter);
}

// A change the server refused because another view edits this root, not taken over (a change to
// the whole view): its marker shows.
export function recordRefusal(rootId, where) {
    if (typeof rootId !== 'string' || rootId === '' || typeof where !== 'string' || where === '') {
        throw new Error('recordRefusal requires the root and where it is edited');
    }
    if (!Object.hasOwn(lockState.lockedRoots, rootId) || lockState.lockedRoots[rootId] !== where) {
        lockState.lockedRoots = { ...lockState.lockedRoots, [rootId]: where };
        renderMarkers();
    }
}

async function askToTakeOver(noteId, isForChange) {
    const response = await fetch(CONFIG.API.NOTES.TAKE_OVER_EDITING, {
        method: 'POST',
        headers: buildSessionHeaders(true),
        body: JSON.stringify({ noteId, isForChange }),
    });
    if (!response.ok) {
        ErrorHandler.handleApiError(null, response);
        throw new HttpRequestError(`Take Over failed with status ${response.status}`);
    }
    const answer = await response.json();
    if (typeof answer.ready !== 'boolean') {
        throw new Error('Take Over answer must say whether it is ready');
    }
    return answer.ready;
}

async function waitUntilTakenOver(rootId, isForChange) {
    let isReady = await askToTakeOver(rootId, isForChange);
    if (!isReady) {
        // A tab of this browser editing it hears at once, not at its next status check.
        askOtherTabsToCheckNow();
    }
    while (!isReady) {
        await new Promise((resolve) => setTimeout(resolve, TAKE_OVER_ASK_MS));
        isReady = await askToTakeOver(rootId, isForChange);
    }
    // A view answer may have shown it free already: the other tab tells this one at once.
    if (Object.hasOwn(lockState.lockedRoots, rootId)) {
        const { [rootId]: _taken, ...others } = lockState.lockedRoots;
        lockState.lockedRoots = others;
    }
    renderMarkers();
}

function endTakeOver() {
    if (lockState.takingOverRootId !== '') lockState.takingOverRootId = '';
    if (lockState.enteringRootId !== '') lockState.enteringRootId = '';
}

async function takeOverThenEnter(rootId, enter) {
    lockState.takingOverRootId = rootId;
    await waitUntilTakenOver(rootId, TAKEN_TO_EDIT);
    lockState.enteringRootId = rootId;
    await CommandGate.runWhenFree('editLock.takeOver', enter);
    endTakeOver();
}

// The wait for the other view to let go is no command: the page stays usable meanwhile, and only
// what was clicked, once the root is free, is one. A failed request ends the take-over (its
// message is shown); anything else is a bug.
function startTakeOver(rootId, enter) {
    void takeOverThenEnter(rootId, enter).catch((error) => {
        rethrowUnexpectedError(error);
        if (!(error instanceof HttpRequestError)) throw error;
        endTakeOver();
    });
}

// A change refused for this root (api-client.js): taken over before it is sent again. Once sent,
// this view's next status check lets the root go unless this view edits in it, so neither view
// holds it (case 6).
export async function takeOverForChange(rootId) {
    if (typeof rootId !== 'string' || rootId === '') {
        throw new Error('takeOverForChange requires the root');
    }
    await waitUntilTakenOver(rootId, TAKEN_FOR_A_CHANGE);
}

function movedTo(where) {
    return where.replace(/^(in|on) /, 'to ');
}

// The status check said another view took this view's root over (case 5): the typing is saved
// (allowed while the server hands over) and edit mode ends with the note where it is; a floating
// message says where editing went. Too late to save (the handover time passed while this tab was
// hidden): the typing is kept on a card for copying instead.
export function leaveTakenOverEditing(lock) {
    if (lock === null || typeof lock !== 'object' || typeof lock.takenWhere !== 'string' || typeof lock.maySave !== 'boolean'
        || typeof lock.isForChange !== 'boolean') {
        throw new Error('A taken-over lock says where editing went, why, and whether this view may save');
    }
    void CommandGate.runWhenFree('editLock.takenOver', async () => {
        // Taken for a fold or a tick there: editing went nowhere, it ended.
        const message = lock.isForChange ? `Editing ended: changed ${lock.takenWhere}` : `Editing moved ${movedTo(lock.takenWhere)}`;
        if (!ModeContext.isEditing) {
            FloatingMessages.show({ text: message, type: 'info', detail: '', isClosable: true, isLasting: false, key: null, action: null });
            return;
        }
        const { actionDeselectNote, actionExitEditingWithoutSavingOrRefreshing } = await import('../actions/selection-actions.js');
        if (lock.maySave || !ModeContext.isDirty) {
            await actionDeselectNote();
            FloatingMessages.show({ text: message, type: 'info', detail: '', isClosable: true, isLasting: false, key: null, action: null });
            return;
        }
        const editor = document.querySelector(`.note[data-note-id="${CSS.escape(ModeContext.currentNoteId)}"] > .note-content`);
        if (!(editor instanceof HTMLElement)) {
            throw new Error('The note being edited is not shown');
        }
        const unsaved = editor.innerText;
        await actionExitEditingWithoutSavingOrRefreshing();
        const { actionRefreshAndMaybeSelect } = await import('../actions/ui-actions.js');
        await actionRefreshAndMaybeSelect({ context: 'edit-lock-taken-over' });
        FloatingMessages.show({
            text: lock.isForChange ? `Not saved: changed ${lock.takenWhere}` : `Not saved: editing moved ${movedTo(lock.takenWhere)}`,
            type: 'error', detail: '',
            isClosable: true, isLasting: true, key: NOT_SAVED_KEY,
            action: { label: 'Copy', onSelect: () => navigator.clipboard.writeText(unsaved) },
        });
    });
}

// Every tab-state answer: the searches other views are typing. The search box of a context whose
// search another view types follows it and cannot be typed in; its tooltip says where (case 10).
export function recordSearchLocks(searchLocks) {
    requireWhereByRoot(searchLocks);
    if (JSON.stringify(searchLocks) !== JSON.stringify(lockState.searchLocks)) {
        lockState.searchLocks = { ...searchLocks };
    }
    showSearchLock();
}

export function showSearchLock() {
    const input = document.getElementById('search-input');
    if (!(input instanceof HTMLInputElement)) {
        return;
    }
    const tabId = ModeContext.activeTabId;
    const isLocked = Object.hasOwn(lockState.searchLocks, tabId);
    input.readOnly = isLocked;
    input.classList.toggle('is-search-locked', isLocked);
    if (isLocked) {
        input.title = `Being typed ${lockState.searchLocks[tabId]}`;
    } else if (input.title !== '') {
        input.removeAttribute('title');
    }
}

// Typing in the search box: the server locks that search for the other views while it is saved.
export function noteSearchTyped() {
    if (!lockState.hasTypedSearch) lockState.hasTypedSearch = true;
}

// The search box left after typing: the other views may type that search again at once, not only
// after the pause.
export async function releaseTypedSearch() {
    if (!lockState.hasTypedSearch) {
        return;
    }
    lockState.hasTypedSearch = false;
    const response = await fetch(CONFIG.API.NOTES.TAB_STATE_SEARCH_LOCK_RELEASE, {
        method: 'POST',
        headers: buildSessionHeaders(true),
    });
    if (!response.ok) {
        ErrorHandler.handleApiError(null, response);
        throw new HttpRequestError(`Releasing the search failed with status ${response.status}`);
    }
}
