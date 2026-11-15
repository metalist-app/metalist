// One editor per root note (multi-view editing step 4; docs/ready-to-build/multi-view-editing.md,
// "Step 4's cases"). Every view answer lists the roots other views edit (lockedRoots, with where);
// each shows a small marker at its top right whose tooltip says where (case 3). A first tap in such a
// root opens the marker into "Editing <where> · Take Over" instead of editing (case 4); Take Over
// asks the server until the other view has saved and left, then edits where first tapped (case 5).
// A change the server refused for a locked root opens that root's marker instead of a banner
// (case 6). The view a root is taken from saves its typing and leaves (leaveTakenOverEditing).
import { ApplicationState } from '../../application-state.js';
import { CONFIG } from '../../config.js';
import { ErrorHandler } from '../../error-handler.js';
import { HttpRequestError } from '../../expected-errors.js';
import { FloatingMessages } from '../../floating-messages.js';
import { buildSessionHeaders } from '../../session-auth.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { CommandGate } from './command-gate-service.js';

const MARKER_CLASS = 'note-edit-lock';
const CARD_CLASS = 'note-edit-lock-card';
const TAKE_OVER_CLASS = 'note-edit-lock-take-over';
const TAKE_OVER_LABEL = 'Take Over';
// Take Over asks this often until the other view has let go (the server answers ready within
// its handover time, edit_locks.py HANDOVER_SECONDS).
const TAKE_OVER_ASK_MS = 300;
const NOT_SAVED_KEY = 'edit-lock-not-saved';

const lockState = ApplicationState.createFields('edit-lock-service', {
    // Root id → where another view edits it ("on your phone", "in another tab", …).
    lockedRoots: {},
    // The root whose marker is open, and what a Take Over there goes on to do.
    openRootId: '',
    enterAfterTakeOver: null,
    isEditedRootMovedElsewhere: false,
    isCloseWatched: false,
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

function rootElement(rootId) {
    return document.querySelector(`#notes-container > .note[data-note-id="${CSS.escape(rootId)}"]`);
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

function closeCard() {
    for (const card of document.querySelectorAll(`.${CARD_CLASS}`)) {
        card.remove();
    }
    if (lockState.openRootId !== '') lockState.openRootId = '';
    if (lockState.enterAfterTakeOver !== null) lockState.enterAfterTakeOver = null;
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
    if (lockState.openRootId !== '' && !Object.hasOwn(lockState.lockedRoots, lockState.openRootId)) {
        closeCard();
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

function watchForClose() {
    if (lockState.isCloseWatched) {
        return;
    }
    lockState.isCloseWatched = true;
    // A press anywhere but on the card closes it, as Escape does.
    document.addEventListener('pointerdown', (event) => {
        if (lockState.openRootId === '' || (event.target instanceof Element && event.target.closest(`.${CARD_CLASS}`))) {
            return;
        }
        closeCard();
    }, { capture: true });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && lockState.openRootId !== '') {
            closeCard();
        }
    }, { capture: true });
}

function openCard(rootId, enterAfterTakeOver) {
    const root = rootElement(rootId);
    if (root === null) {
        return false;
    }
    closeCard();
    watchForClose();
    const card = document.createElement('div');
    card.className = CARD_CLASS;
    const text = card.appendChild(document.createElement('span'));
    text.textContent = `Editing ${lockState.lockedRoots[rootId]}`;
    const button = card.appendChild(document.createElement('button'));
    button.type = 'button';
    button.className = TAKE_OVER_CLASS;
    button.textContent = TAKE_OVER_LABEL;
    button.addEventListener('click', (event) => {
        event.stopPropagation();
        event.preventDefault();
        void CommandGate.run('editLock.takeOver', () => takeOver(rootId));
    });
    root.appendChild(card);
    // A state set again is refused: set only what changes.
    if (lockState.openRootId !== rootId) lockState.openRootId = rootId;
    if (lockState.enterAfterTakeOver !== enterAfterTakeOver) lockState.enterAfterTakeOver = enterAfterTakeOver;
    return true;
}

// Entering edit mode in a root another view edits: the marker opens instead (case 4), and Take
// Over goes on with enter. True when it did, so the caller does not edit.
export function openMarkerInsteadOfEditing(noteId, enter) {
    if (typeof enter !== 'function') {
        throw new Error('openMarkerInsteadOfEditing requires what Take Over goes on to do');
    }
    const rootId = rootIdOfNote(noteId);
    if (rootId === '' || !Object.hasOwn(lockState.lockedRoots, rootId)) {
        return false;
    }
    return openCard(rootId, enter);
}

// A change the server refused because another view edits this root (case 6): its marker opens,
// with nothing to go on to. False when the root is not shown here: the refusal's message says it.
export function openMarkerForRefusal(rootId, where) {
    if (typeof rootId !== 'string' || rootId === '' || typeof where !== 'string' || where === '') {
        throw new Error('openMarkerForRefusal requires the root and where it is edited');
    }
    if (!Object.hasOwn(lockState.lockedRoots, rootId) || lockState.lockedRoots[rootId] !== where) {
        lockState.lockedRoots = { ...lockState.lockedRoots, [rootId]: where };
        renderMarkers();
    }
    return openCard(rootId, null);
}

async function askToTakeOver(noteId) {
    const response = await fetch(CONFIG.API.NOTES.TAKE_OVER_EDITING, {
        method: 'POST',
        headers: buildSessionHeaders(true),
        body: JSON.stringify({ noteId }),
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

async function takeOver(rootId) {
    const enter = lockState.enterAfterTakeOver;
    const button = document.querySelector(`.${CARD_CLASS} .${TAKE_OVER_CLASS}`);
    if (button !== null) button.disabled = true;
    while (!(await askToTakeOver(rootId))) {
        await new Promise((resolve) => setTimeout(resolve, TAKE_OVER_ASK_MS));
    }
    const { [rootId]: taken, ...others } = lockState.lockedRoots;
    if (typeof taken !== 'string') {
        throw new Error(`Root ${rootId} was taken over without being locked`);
    }
    lockState.lockedRoots = others;
    closeCard();
    renderMarkers();
    if (enter !== null) {
        await enter();
    }
}

function movedTo(where) {
    return where.replace(/^(in|on) /, 'to ');
}

// The status check said another view took this view's root over (case 5): the typing is saved
// (allowed while the server hands over) and edit mode ends with the note where it is; a floating
// message says where editing went. Too late to save (the handover time passed while this tab was
// hidden): the typing is kept on a card for copying instead.
export function leaveTakenOverEditing(lock) {
    if (lock === null || typeof lock !== 'object' || typeof lock.takenWhere !== 'string' || typeof lock.maySave !== 'boolean') {
        throw new Error('A taken-over lock says where editing went and whether this view may save');
    }
    void CommandGate.runWhenFree('editLock.takenOver', async () => {
        const message = `Editing moved ${movedTo(lock.takenWhere)}`;
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
            text: `Not saved: ${message.charAt(0).toLowerCase()}${message.slice(1)}`, type: 'error', detail: '',
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
