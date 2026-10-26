import { ApplicationState, stateValuesEqual } from '../../application-state.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';
import { NotesAPI } from '../../api-client.js';
import { unlessDiagramEditorOpen } from '../../excalidraw/excalidraw-editor-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
// Placed as the paste format card is: below its anchor, or above it near the window's bottom.
import { placePasteFormatOffer } from './paste-format-offer-service.js';

// Typing `[[` in a note opens a list of notes to reference (docs/ui/references.md,
// "Suggestions"); what is typed after it narrows the list, and choosing a note
// replaces `[[` and the typed text with `[[UUID]]`. The list sits just below the
// `[[`, or above it near the window's bottom, so it stays put while the user
// types, and never moves the page. ↑/↓ move through it, Enter or Tab chooses,
// Escape closes it and leaves the text; so does moving the caret away from the
// `[[`. Nothing matching shows no list. `[[@` starts a wrapper tag ([[@LaTeX]]),
// not a reference, so it opens nothing.

const TRIGGER = '[[';
const WRAPPER_TAG_START = '@';
// Longer text after `[[` is not a note being looked for.
const MAX_QUERY_LENGTH = 80;
// Typed text settles this long before the list is asked for.
const REQUEST_DELAY_MS = 100;
const EDIT_CHECK_INTERVAL_MS = 300;
const PASSWORD = 'password';
const USERNAME = 'username';
// The credential notes' icons, as the note itself shows them (content_formatting.py).
const CREDENTIAL_ICON_PATHS = {
    [USERNAME]: 'M12 12c2.761 0 5-2.239 5-5s-2.239-5-5-5-5 2.239-5 5 2.239 5 5 5Zm0 2c-3.866 0-7 2.239-7 5v3h14v-3c0-2.761-3.134-5-7-5Z',
    [PASSWORD]: 'M7 10V7a5 5 0 0110 0v3h1a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2v-8a2 2 0 012-2h1zm2 0h6V7a3 3 0 00-6 0v3z',
};
const CREDENTIAL_LABELS = { [USERNAME]: 'Username', [PASSWORD]: 'Password' };
const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const NO_SELECTION = -1;
const MAIN_BUTTON = 0;

const moduleState = ApplicationState.createFields('reference-suggestions-service', {
    initialized: false,
    // The catalog of notes is built on the server the first time it is asked for:
    // asked for at the first typing in a note, it is ready by the time `[[` is.
    warmed: false,
    list: null,
    noteId: null,
    // The `[[` the list is for: its text node and place in it, and the text typed after it.
    triggerNode: null,
    triggerStart: NO_SELECTION,
    query: null,
    // The query the list on screen was built for.
    listQuery: null,
    suggestions: [],
    selectedIndex: NO_SELECTION,
    // A `[[` whose list Escape closed stays closed.
    dismissedNode: null,
    dismissedStart: NO_SELECTION,
    // A press began on the list: its release and click are the list's too.
    isPressOnList: false,
    pendingTimer: null,
    requestSerial: 0,
    requestController: null,
    editCheckTimer: null,
});

function setState(field, value) {
    if (!stateValuesEqual(moduleState[field], value)) moduleState[field] = value;
}

function editedContent(noteId) {
    const content = document.querySelector(`.note[data-note-id="${noteId}"] > .note-content`);
    if (!(content instanceof HTMLElement)) {
        throw new Error(`Edited note content missing: ${noteId}`);
    }
    return content;
}

// The `[[` before the caret and the text typed after it, or null.
function triggerAtCaret(content) {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0 || !selection.isCollapsed) return null;
    const node = selection.anchorNode;
    if (!(node instanceof Text) || !content.contains(node)) return null;
    const before = node.data.slice(0, selection.anchorOffset);
    const start = before.lastIndexOf(TRIGGER);
    if (start < 0) return null;
    const query = before.slice(start + TRIGGER.length);
    if (query.length > MAX_QUERY_LENGTH || /[[\]\n]/.test(query) || query.startsWith(WRAPPER_TAG_START)) return null;
    return { node, start, end: selection.anchorOffset, query };
}

function cancelRequest() {
    if (moduleState.pendingTimer !== null) {
        clearTimeout(moduleState.pendingTimer);
        moduleState.pendingTimer = null;
    }
    if (moduleState.requestController !== null) {
        moduleState.requestController.abort();
        moduleState.requestController = null;
    }
    moduleState.requestSerial += 1;
}

function hideList() {
    if (moduleState.list !== null) {
        moduleState.list.remove();
        moduleState.list = null;
    }
    setState('listQuery', null);
    setState('suggestions', []);
    setState('selectedIndex', NO_SELECTION);
}

export function closeReferenceSuggestions() {
    cancelRequest();
    hideList();
    setState('noteId', null);
    setState('triggerNode', null);
    setState('triggerStart', NO_SELECTION);
    setState('query', null);
    if (moduleState.editCheckTimer !== null) {
        clearInterval(moduleState.editCheckTimer);
        moduleState.editCheckTimer = null;
    }
}

export function isReferenceSuggestionListOpen() {
    return moduleState.list !== null;
}

function anchorRect(node, start) {
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + TRIGGER.length);
    return range.getBoundingClientRect();
}

function placeList() {
    const list = moduleState.list;
    const { left, top } = placePasteFormatOffer({
        anchor: anchorRect(moduleState.triggerNode, moduleState.triggerStart),
        width: list.offsetWidth, height: list.offsetHeight,
        viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
    });
    list.style.left = `${left}px`;
    list.style.top = `${top}px`;
}

function credentialIcon(credential) {
    const icon = document.createElement('span');
    icon.className = 'reference-suggestion-icon';
    icon.setAttribute('role', 'img');
    icon.setAttribute('aria-label', CREDENTIAL_LABELS[credential]);
    const svg = document.createElementNS(SVG_NAMESPACE, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(SVG_NAMESPACE, 'path');
    path.setAttribute('fill', 'currentColor');
    path.setAttribute('d', CREDENTIAL_ICON_PATHS[credential]);
    svg.appendChild(path);
    icon.appendChild(svg);
    return icon;
}

function requireSuggestion(suggestion) {
    if (!suggestion || typeof suggestion !== 'object') {
        throw new Error('Reference suggestion missing');
    }
    for (const field of ['noteId', 'firstLine', 'context', 'snippet', 'credential']) {
        if (typeof suggestion[field] !== 'string') {
            throw new Error(`Reference suggestion requires ${field}`);
        }
    }
    if (!Number.isInteger(suggestion.highlightStart) || !Number.isInteger(suggestion.highlightEnd)) {
        throw new Error('Reference suggestion requires its highlight');
    }
    if (suggestion.credential !== '' && !Object.hasOwn(CREDENTIAL_ICON_PATHS, suggestion.credential)) {
        throw new Error(`Unknown credential in a reference suggestion: ${suggestion.credential}`);
    }
    return suggestion;
}

// Every text is set as text, never as HTML.
function buildItem(suggestion, index) {
    const item = document.createElement('div');
    item.className = 'reference-suggestion';
    item.setAttribute('role', 'option');
    item.dataset.noteId = suggestion.noteId;
    const title = document.createElement('div');
    title.className = 'reference-suggestion-title';
    if (suggestion.credential !== '') {
        title.appendChild(credentialIcon(suggestion.credential));
    }
    const titleText = document.createElement('span');
    titleText.className = 'reference-suggestion-text';
    titleText.textContent = suggestion.firstLine;
    title.appendChild(titleText);
    item.appendChild(title);
    if (suggestion.context !== '') {
        const context = document.createElement('div');
        context.className = 'reference-suggestion-context';
        context.textContent = suggestion.context;
        item.appendChild(context);
    }
    if (suggestion.snippet !== '') {
        const snippet = document.createElement('div');
        snippet.className = 'reference-suggestion-snippet';
        const { snippet: text, highlightStart, highlightEnd } = suggestion;
        const match = document.createElement('mark');
        match.textContent = text.slice(highlightStart, highlightEnd);
        snippet.append(text.slice(0, highlightStart), match, text.slice(highlightEnd));
        item.appendChild(snippet);
    }
    item.dataset.index = String(index);
    return item;
}

function showSelection() {
    moduleState.list.querySelectorAll('.reference-suggestion').forEach((item, index) => {
        const isSelected = index === moduleState.selectedIndex;
        item.classList.toggle('is-selected', isSelected);
        item.setAttribute('aria-selected', String(isSelected));
    });
}

function renderList(query, suggestions) {
    hideList();
    if (suggestions.length === 0) return;
    const list = document.createElement('div');
    list.className = 'reference-suggestions';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Notes to reference');
    suggestions.forEach((suggestion, index) => list.appendChild(buildItem(suggestion, index)));
    list.style.left = '0px';
    list.style.top = '0px';
    document.body.appendChild(list);
    moduleState.list = list;
    setState('listQuery', query);
    setState('suggestions', suggestions);
    setState('selectedIndex', 0);
    showSelection();
    placeList();
}

async function requestSuggestions(query, noteId) {
    const requestId = moduleState.requestSerial;
    const controller = new AbortController();
    moduleState.requestController = controller;
    const response = await NotesAPI.fetchReferenceSuggestions(query, noteId, controller.signal).catch((error) => {
        rethrowUnexpectedError(error);
        if (error && error.name === 'AbortError') return null;
        throw error;
    });
    if (moduleState.requestController === controller) moduleState.requestController = null;
    if (response === null || requestId !== moduleState.requestSerial) return;
    if (!response || !Array.isArray(response.suggestions)) {
        throw new Error('Reference suggestions response requires suggestions');
    }
    renderList(query, response.suggestions.map(requireSuggestion));
}

function warmCatalog(noteId) {
    moduleState.warmed = true;
    NotesAPI.fetchReferenceSuggestions('', noteId, new AbortController().signal).catch((error) => {
        rethrowUnexpectedError(error);
        throw error;
    });
}

function checkStillEditing() {
    if (moduleState.noteId === null || !ModeContext.isEditingNote(moduleState.noteId)) {
        closeReferenceSuggestions();
    }
}

// Look at the text before the caret in the note being edited: open, narrow or close the list.
export function updateReferenceSuggestions(content, noteId) {
    if (!(content instanceof HTMLElement) || typeof noteId !== 'string' || noteId === '') {
        throw new Error('updateReferenceSuggestions requires the edited note and its content');
    }
    if (!moduleState.warmed) warmCatalog(noteId);
    const trigger = triggerAtCaret(content);
    const isDismissed = trigger !== null && trigger.node === moduleState.dismissedNode
        && trigger.start === moduleState.dismissedStart;
    if (trigger === null || isDismissed) {
        if (moduleState.noteId !== null) closeReferenceSuggestions();
        return;
    }
    const isSameTrigger = moduleState.triggerNode === trigger.node && moduleState.triggerStart === trigger.start;
    if (isSameTrigger && moduleState.query === trigger.query && moduleState.noteId === noteId) return;
    askForList(trigger, noteId);
}

// A new `[[`, or new text after it: the list for it, once the typing settles.
function askForList(trigger, noteId) {
    cancelRequest();
    setState('noteId', noteId);
    setState('triggerNode', trigger.node);
    setState('triggerStart', trigger.start);
    setState('query', trigger.query);
    if (moduleState.editCheckTimer === null) {
        moduleState.editCheckTimer = setInterval(checkStillEditing, EDIT_CHECK_INTERVAL_MS);
    }
    moduleState.pendingTimer = setTimeout(async () => {
        moduleState.pendingTimer = null;
        await requestSuggestions(trigger.query, noteId);
    }, REQUEST_DELAY_MS);
}

// The caret moved without typing (arrow keys, a click): the list follows it.
function handleSelectionChange() {
    const noteId = moduleState.noteId;
    if (noteId === null) return;
    const content = document.querySelector(`.note[data-note-id="${noteId}"] > .note-content`);
    if (!ModeContext.isEditingNote(noteId) || !(content instanceof HTMLElement)) {
        closeReferenceSuggestions();
        return;
    }
    updateReferenceSuggestions(content, noteId);
}

// Replace `[[` and the text typed after it with the chosen note's reference, as typing it would.
function choose(index) {
    const suggestion = moduleState.suggestions[index];
    const trigger = triggerAtCaret(editedContent(moduleState.noteId));
    if (trigger === null || trigger.node !== moduleState.triggerNode || trigger.start !== moduleState.triggerStart) {
        throw new Error('The `[[` a reference suggestion was chosen for is gone');
    }
    const reference = `${TRIGGER}${suggestion.noteId}]]`;
    closeReferenceSuggestions();
    const range = document.createRange();
    range.setStart(trigger.node, trigger.start);
    range.setEnd(trigger.node, trigger.end);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    const showDefaultUi = false;
    if (!document.execCommand('insertText', showDefaultUi, reference)) {
        throw new Error('Inserting the chosen reference failed');
    }
}

function moveSelection(step) {
    const last = moduleState.suggestions.length - 1;
    setState('selectedIndex', Math.min(last, Math.max(0, moduleState.selectedIndex + step)));
    showSelection();
}

// The event is the list's alone.
function stopEvent(event) {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
}

function dismiss() {
    setState('dismissedNode', moduleState.triggerNode);
    setState('dismissedStart', moduleState.triggerStart);
    closeReferenceSuggestions();
}

function isListKey(event) {
    const hasModifier = [event.shiftKey, event.metaKey, event.ctrlKey, event.altKey].includes(true);
    return !hasModifier && ['ArrowDown', 'ArrowUp', 'Enter', 'Tab'].includes(event.key);
}

function handleKeyDown(event) {
    if (moduleState.list === null || event.isComposing) return;
    if (event.key === 'Escape') {
        stopEvent(event);
        dismiss();
        return;
    }
    if (!isListKey(event)) return;
    // Only a list built for the text typed is acted on: Enter on an older list
    // goes into the note as usual, and the arrows wait for the new list.
    if (moduleState.listQuery !== moduleState.query) {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') stopEvent(event);
        return;
    }
    stopEvent(event);
    if (event.key === 'ArrowDown') moveSelection(1);
    else if (event.key === 'ArrowUp') moveSelection(-1);
    else choose(moduleState.selectedIndex);
}

// A press on the list is the list's alone: it keeps the caret in the note, and
// MetaList would take it for a press outside the edited note. Pressing an item
// chooses it; a press anywhere else closes the list.
function handleMouseDown(event) {
    if (moduleState.list === null) return;
    if (!(event.target instanceof Element) || !moduleState.list.contains(event.target)) {
        closeReferenceSuggestions();
        return;
    }
    stopEvent(event);
    setState('isPressOnList', true);
    const item = event.target.closest('.reference-suggestion');
    if (item !== null && event.button === MAIN_BUTTON) choose(Number(item.dataset.index));
}

// The rest of a press on the list (its release and click) is the list's too,
// though choosing removed the list from under the pointer.
function swallowRelease(event) {
    if (!moduleState.isPressOnList) return;
    stopEvent(event);
    if (event.type === 'mouseup') {
        // Its click, if any, follows at once.
        setTimeout(() => setState('isPressOnList', false), 0);
    }
}

function followAnchor() {
    if (moduleState.list !== null) placeList();
}

export function initializeReferenceSuggestions() {
    if (moduleState.initialized) return;
    moduleState.initialized = true;
    window.addEventListener('keydown', unlessDiagramEditorOpen(handleKeyDown), { capture: true });
    window.addEventListener('mousedown', handleMouseDown, { capture: true });
    window.addEventListener('mouseup', swallowRelease, { capture: true });
    window.addEventListener('click', swallowRelease, { capture: true });
    document.addEventListener('selectionchange', handleSelectionChange);
    document.addEventListener('scroll', followAnchor, { capture: true });
    window.addEventListener('resize', followAnchor);
}
