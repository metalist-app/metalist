import { ApplicationState } from '../application-state.js';
import { CommandPalette } from '../command-palette/command-palette-controller.js';
import { NotesAPI } from '../api-client.js';
import { escapeHtml } from '../html-escape.js';
import { ModeContextInstance as ModeContext } from '../mode-manager/mode-context.js';
import { CommandGate } from '../mode-manager/services/command-gate-service.js';
import { expandNote } from '../mode-manager/actions/note-actions.js';
import { actionRefreshAndMaybeSelect } from '../mode-manager/actions/ui-actions.js';
import { syncSearchInputValue } from '../mode-manager/services/search-input-service.js';
import { getSearchSuggestionWindowDays } from '../mode-manager/services/search-suggestion-windows-service.js';
import { splitTagsForDisplay } from '../mode-manager/services/tag-syntax-service.js';
import { sanitizeTags } from '../mode-manager/services/tag-bar-service.js';
import {
    ROOT_SORT_MODES,
    baseRootSortMode,
    isRootSortModeReversed,
    rootSortModeWithDirection,
} from '../mode-manager/services/root-sort-service.js';
import { DATE_RANGE_KINDS, DATE_RANGE_PRESETS } from '../mode-manager/services/date-range-kinds.js';
import { FILE_FILTER_CHOICES, FILE_FILTER_KINDS } from '../mode-manager/services/file-filter-kinds.js';
import { searchTermsOf, withSearchTerm, withoutSearchTerm } from './phone-search-terms.js';

// The phone prototype (docs/ready-to-build/phone-prototype.md, phone-prototype-mocks.html):
// under 640 px the body gets .phone-layout and the page becomes a read-only view of the notes
// plus capture. A tap never edits; it shows a note's own tags as pills. Desktop is unchanged.

const PHONE_MEDIA_QUERY = '(max-width: 640px)';
const PHONE_CLASS = 'phone-layout';
// Temporary developer switch (not a user setting): what tapping a tag pill does.
const TAG_PILL_SWITCH = 'metalist.dev.phoneTagPills';
const NARROW_TAG_PILLS = 'narrow';
// A capture with no tags is tagged @inbox: a reserved meta tag (the maintainer, 2026-10-24),
// not inherited by children (docs/ui/search-semantics.md), so search @inbox for what to sort.
const INBOX_TAG = '@inbox';
const SHEET_MODAL = 'phoneSheet';
const CAPTURE_MODAL = 'phoneCapture';
const MAX_CAPTURE_SUGGESTIONS = 6;
// A typed search counts as one step back once it has stopped changing for this long.
const SEARCH_SETTLE_MS = 1000;

const SORT_ROWS = [[ROOT_SORT_MODES.NORMAL, 'Normal'], [ROOT_SORT_MODES.CREATED, 'Created']];
const MORE_SORT_ROWS = [
    [ROOT_SORT_MODES.UPDATED, 'Updated'],
    [ROOT_SORT_MODES.ALPHABETICAL, 'A–Z'],
    [ROOT_SORT_MODES.CONTENT_VOLUME, 'Size'],
];

// Under the date and file menus: what each current choice is called.
const DATE_VALUE_LABELS = new Map([
    [DATE_RANGE_KINDS.NONE, 'All Dates'],
    [DATE_RANGE_KINDS.CUSTOM, 'Custom'],
    ...DATE_RANGE_PRESETS,
]);
const FILE_VALUE_LABELS = new Map([[FILE_FILTER_KINDS.NONE, 'All Notes'], ...FILE_FILTER_CHOICES]);

function valueLabel(labels, value) {
    if (!labels.has(value)) {
        throw new Error(`No label for menu value ${value}`);
    }
    return labels.get(value);
}

const phoneState = ApplicationState.createFields('phone-mode', {
    isInstalled: false,
    // Notes whose own tags show as pills under them.
    tagNoteIds: [],
    // The search the history entry on top records.
    historyQuery: null,
    settleTimer: null,
    captureTags: [],
    captureSuggestionSerial: 0,
});

function isPhone() {
    return document.body.classList.contains(PHONE_CLASS);
}

function requireElement(id) {
    const element = document.getElementById(id);
    if (!(element instanceof HTMLElement)) {
        throw new Error(`Phone layout element missing: ${id}`);
    }
    return element;
}

// --- Searching -------------------------------------------------------------------------

function runSearch(query) {
    const input = requireElement('search-input');
    syncSearchInputValue(input, query);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

// The search now shown becomes a step back, unless it already is one.
function recordSettledSearch() {
    if (phoneState.settleTimer !== null) {
        window.clearTimeout(phoneState.settleTimer);
        phoneState.settleTimer = null;
    }
    const query = requireElement('search-input').value;
    if (isPhone() && query !== phoneState.historyQuery) {
        window.history.pushState({ phoneSearch: query }, '');
        phoneState.historyQuery = query;
    }
}

function onSearchQueryChanged() {
    renderSearchPills();
    if (phoneState.settleTimer !== null) {
        window.clearTimeout(phoneState.settleTimer);
    }
    phoneState.settleTimer = window.setTimeout(recordSettledSearch, SEARCH_SETTLE_MS);
}

// A search the phone made (a pill): its own history entry, after the one it leaves.
function searchFromPhone(query) {
    recordSettledSearch();
    if (query !== phoneState.historyQuery) {
        window.history.pushState({ phoneSearch: query }, '');
        phoneState.historyQuery = query;
    }
    runSearch(query);
    renderSearchPills();
}

function onHistoryBack(event) {
    if (!isPhone() || event.state === null || typeof event.state.phoneSearch !== 'string') {
        return;
    }
    if (phoneState.historyQuery !== event.state.phoneSearch) {
        phoneState.historyQuery = event.state.phoneSearch;
    }
    runSearch(event.state.phoneSearch);
    renderSearchPills();
}

function renderSearchPills() {
    const row = document.querySelector('.search-input-row');
    const pills = requireElement('phone-search-pills');
    const input = requireElement('search-input');
    const terms = searchTermsOf(input.value);
    const showsPills = isPhone() && terms.length > 0 && document.activeElement !== input;
    row.classList.toggle('phone-search-has-pills', showsPills);
    pills.innerHTML = terms.map((term, index) => `
        <span class="phone-search-pill${term.isExclusion ? ' is-exclusion' : ''}" data-term="${escapeHtml(term.text)}" data-term-index="${index}">
            <span class="phone-search-pill-text">${escapeHtml(term.text)}</span>
            <button type="button" class="phone-search-pill-remove" aria-label="Remove ${escapeHtml(term.text)}">×</button>
        </span>`).join('');
}

function onSearchPillsTap(event) {
    const remove = event.target.closest('.phone-search-pill-remove');
    event.preventDefault();
    event.stopPropagation();
    if (remove === null) {
        // A tap on the pills, not on an ×: type in the search again.
        const input = requireElement('search-input');
        document.querySelector('.search-input-row').classList.remove('phone-search-has-pills');
        input.focus();
        return;
    }
    const index = Number(remove.closest('.phone-search-pill').dataset.termIndex);
    searchFromPhone(withoutSearchTerm(requireElement('search-input').value, index));
}

// --- Tapping notes ---------------------------------------------------------------------

function updateReadOnlyLabel() {
    const isHidden = phoneState.tagNoteIds.length === 0;
    const label = requireElement('phone-readonly');
    if (label.hidden !== isHidden) {
        label.hidden = isHidden;
    }
}

function noteTagsHtml(tags) {
    const pieces = splitTagsForDisplay(tags).filter((piece) => piece.kind !== 'comment');
    if (pieces.length === 0) {
        return '<span class="phone-no-tags">No tags</span>';
    }
    return pieces.map((piece) => `<button type="button" class="phone-tag-pill" data-tag="${escapeHtml(piece.text)}">${escapeHtml(piece.text)}</button>`).join('');
}

function showNoteTags(note) {
    const content = note.querySelector(':scope > .note-content');
    if (content === null || note.querySelector(':scope > .phone-note-tags') !== null) {
        return;
    }
    const pills = document.createElement('div');
    pills.className = 'phone-note-tags';
    pills.innerHTML = noteTagsHtml(note.dataset.noteTags);
    content.after(pills);
}

function toggleNoteTags(note) {
    const noteId = note.dataset.noteId;
    if (phoneState.tagNoteIds.includes(noteId)) {
        phoneState.tagNoteIds = phoneState.tagNoteIds.filter((id) => id !== noteId);
        note.querySelector(':scope > .phone-note-tags')?.remove();
        updateReadOnlyLabel();
        return;
    }
    phoneState.tagNoteIds = [...phoneState.tagNoteIds, noteId];
    showNoteTags(note);
    updateReadOnlyLabel();
    if (note.dataset.hasChildren === 'true' && note.dataset.isCollapsed === 'true') {
        void CommandGate.run('phone.expand_note', async () => {
            await expandNote(noteId);
        });
    }
}

// Redrawing the list replaces notes; the tags shown stay shown.
function keepNoteTagsShown() {
    const notes = phoneState.tagNoteIds
        .map((noteId) => document.querySelector(`#notes-container .note[data-note-id="${CSS.escape(noteId)}"]`))
        .filter((note) => note !== null);
    if (notes.length !== phoneState.tagNoteIds.length) {
        phoneState.tagNoteIds = notes.map((note) => note.dataset.noteId);
    }
    for (const note of notes) {
        showNoteTags(note);
    }
    updateReadOnlyLabel();
}

function searchFromTagPill(tag) {
    const isNarrowing = window.localStorage.getItem(TAG_PILL_SWITCH) === NARROW_TAG_PILLS;
    const current = requireElement('search-input').value;
    if (phoneState.tagNoteIds.length > 0) {
        phoneState.tagNoteIds = [];
    }
    updateReadOnlyLabel();
    searchFromPhone(isNarrowing ? withSearchTerm(current, tag) : tag);
}

// Runs before the app's own handlers (window, capture phase): on the phone a tap on a note
// shows its tags and never selects or edits it.
function onNoteInteraction(event) {
    if (!isPhone() || !(event.target instanceof Element)) {
        return;
    }
    const note = event.target.closest('#notes-container .note');
    if (note === null || event.target.closest('.note-collapse-toggle') !== null) {
        return;
    }
    event.stopImmediatePropagation();
    if (event.target.closest('a[href]') !== null) {
        return;
    }
    event.preventDefault();
    if (event.type !== 'click') {
        return;
    }
    const tagPill = event.target.closest('.phone-tag-pill');
    if (tagPill !== null) {
        searchFromTagPill(tagPill.dataset.tag);
        return;
    }
    toggleNoteTags(note);
}

// No menus on the phone: they offer editing, which the phone never does.
function onContextMenu(event) {
    if (!isPhone()) {
        return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
}

// --- The menu sheet --------------------------------------------------------------------

function choiceHtml(choice, label, isCurrent) {
    return `<button type="button" class="phone-sheet-row" data-phone-choice="${escapeHtml(choice)}">`
        + `<span>${escapeHtml(label)}</span>${isCurrent ? '<span class="phone-sheet-check" aria-label="current">✓</span>' : ''}</button>`;
}

function disclosureHtml(group, label, value) {
    return `<button type="button" class="phone-sheet-row phone-sheet-disclosure" data-phone-group="${escapeHtml(group)}">`
        + `<span>${escapeHtml(label)}</span><span class="phone-sheet-value">${escapeHtml(value)} ›</span></button>`;
}

function sheetHtml() {
    const sortMode = CommandPalette.getSortMode();
    const currentSort = baseRootSortMode(sortMode);
    const isReversed = isRootSortModeReversed(sortMode);
    const dateKind = CommandPalette.getDateRangeKind();
    const fileKind = CommandPalette.getFileFilterKind();
    const moreLabels = MORE_SORT_ROWS.map(([, label]) => label).join(' · ');
    return `
        <div class="phone-sheet-handle" aria-hidden="true"></div>
        <p class="phone-sheet-heading">Sort order</p>
        ${SORT_ROWS.map(([mode, label]) => choiceHtml(`sort:${mode}`, label, mode === currentSort)).join('')}
        ${disclosureHtml('sort-more', moreLabels, '')}
        <div class="phone-sheet-group" data-phone-group-items="sort-more" hidden>
            ${MORE_SORT_ROWS.map(([mode, label]) => choiceHtml(`sort:${mode}`, label, mode === currentSort)).join('')}
        </div>
        ${choiceHtml('sort:reverse', 'Reverse', isReversed)}
        ${disclosureHtml('date', 'Date Range', valueLabel(DATE_VALUE_LABELS, dateKind))}
        <div class="phone-sheet-group" data-phone-group-items="date" hidden>
            ${choiceHtml(`date:${DATE_RANGE_KINDS.NONE}`, 'Any Date', dateKind === DATE_RANGE_KINDS.NONE)}
            ${DATE_RANGE_PRESETS.map(([kind, label]) => choiceHtml(`date:${kind}`, label, kind === dateKind)).join('')}
        </div>
        ${disclosureHtml('files', 'Notes with Files', valueLabel(FILE_VALUE_LABELS, fileKind))}
        <div class="phone-sheet-group" data-phone-group-items="files" hidden>
            ${choiceHtml(`files:${FILE_FILTER_KINDS.NONE}`, 'All Notes', fileKind === FILE_FILTER_KINDS.NONE)}
            ${FILE_FILTER_CHOICES.map(([kind, label]) => choiceHtml(`files:${kind}`, label, kind === fileKind)).join('')}
        </div>
        ${choiceHtml('untagged', 'Untagged Notes', CommandPalette.getIsUntaggedView())}
        <div class="phone-sheet-buttons">
            <button type="button" class="secondary-btn" data-phone-choice="lock">Lock</button>
            <button type="button" class="secondary-btn" data-phone-choice="sign-out">Sign Out</button>
        </div>`;
}

function openSheet() {
    const sheet = requireElement('phone-sheet');
    sheet.innerHTML = sheetHtml();
    sheet.hidden = false;
    requireElement('phone-sheet-backdrop').hidden = false;
    ModeContext.pushModal(SHEET_MODAL);
}

function closeSheet() {
    requireElement('phone-sheet').hidden = true;
    requireElement('phone-sheet-backdrop').hidden = true;
    ModeContext.removeModal(SHEET_MODAL);
}

function applyChoice(choice) {
    const sortMode = CommandPalette.getSortMode();
    const [kind, value] = choice.split(':');
    if (kind === 'sort' && value === 'reverse') {
        return () => CommandPalette.setSortMode(rootSortModeWithDirection(baseRootSortMode(sortMode), !isRootSortModeReversed(sortMode)));
    }
    if (kind === 'sort') {
        return () => CommandPalette.setSortMode(rootSortModeWithDirection(value, isRootSortModeReversed(sortMode)));
    }
    if (kind === 'date') {
        return () => CommandPalette.setDateRangePreset(value);
    }
    if (kind === 'files') {
        return () => CommandPalette.setFileFilter(value);
    }
    if (kind === 'untagged') {
        return () => CommandPalette.setIsUntaggedView(!CommandPalette.getIsUntaggedView());
    }
    // Lock and Sign Out both log out; each vault has its own address, so the vault stays picked.
    if (kind === 'lock' || kind === 'sign-out') {
        return () => CommandPalette.logout();
    }
    throw new Error(`Unknown phone menu choice: ${choice}`);
}

function onSheetTap(event) {
    const group = event.target.closest('[data-phone-group]');
    if (group !== null) {
        const items = requireElement('phone-sheet').querySelector(`[data-phone-group-items="${group.dataset.phoneGroup}"]`);
        items.hidden = !items.hidden;
        return;
    }
    const choiceButton = event.target.closest('[data-phone-choice]');
    if (choiceButton === null) {
        return;
    }
    const choice = choiceButton.dataset.phoneChoice;
    const run = applyChoice(choice);
    closeSheet();
    // Logging out runs its own command (one at a time): inside another it would be dropped.
    if (choice === 'lock' || choice === 'sign-out') {
        void run();
        return;
    }
    void CommandGate.run('phone.menu_choice', async () => {
        await run();
    });
}

// --- Capture ---------------------------------------------------------------------------

function captureHtml() {
    return `
        <div class="modal-content phone-capture-content">
            <h3>Capture</h3>
            <textarea id="phone-capture-text" rows="5" aria-label="Note"></textarea>
            <label for="phone-capture-tags" class="phone-capture-label">Tags (optional)</label>
            <div class="phone-capture-tag-line">
                <span class="phone-capture-tag-pills"></span>
                <input id="phone-capture-tags" type="text" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false">
            </div>
            <div class="phone-capture-suggestions"></div>
            <div class="form-actions dialog-actions">
                <button type="button" class="secondary-btn" id="phone-capture-cancel">Cancel</button>
                <button type="button" class="primary-btn" id="phone-capture-save">Save</button>
            </div>
        </div>`;
}

function renderCaptureTags() {
    const pills = requireElement('phone-capture').querySelector('.phone-capture-tag-pills');
    pills.innerHTML = phoneState.captureTags.map((tag) => `<span class="phone-capture-tag-pill">${escapeHtml(tag)}</span>`).join('');
}

function addCaptureTag(tag) {
    const clean = sanitizeTags(tag).trim();
    if (clean !== '' && !phoneState.captureTags.includes(clean)) {
        phoneState.captureTags = [...phoneState.captureTags, clean];
    }
    renderCaptureTags();
}

async function suggestCaptureTags(prefix) {
    const suggestions = requireElement('phone-capture').querySelector('.phone-capture-suggestions');
    phoneState.captureSuggestionSerial += 1;
    const serial = phoneState.captureSuggestionSerial;
    if (prefix === '') {
        suggestions.innerHTML = '';
        return;
    }
    const response = await NotesAPI.fetchSearchSuggestions(prefix, getSearchSuggestionWindowDays());
    if (serial !== phoneState.captureSuggestionSerial || !Array.isArray(response.suggestions)) {
        return;
    }
    const tags = response.suggestions.filter((tag) => typeof tag === 'string').slice(0, MAX_CAPTURE_SUGGESTIONS);
    suggestions.innerHTML = tags.map((tag) => `<button type="button" class="phone-tag-pill" data-capture-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`).join('');
}

function onCaptureTagsInput(event) {
    const input = event.target;
    const parts = input.value.split(/\s+/u);
    const typing = parts.pop();
    for (const part of parts) {
        addCaptureTag(part);
    }
    if (input.value !== typing) {
        input.value = typing;
    }
    void suggestCaptureTags(typing);
}

function onCaptureTagsKeyDown(event) {
    if (event.key === 'Backspace' && event.target.value === '' && phoneState.captureTags.length > 0) {
        phoneState.captureTags = phoneState.captureTags.slice(0, -1);
        renderCaptureTags();
    }
}

function openCapture() {
    const capture = requireElement('phone-capture');
    capture.innerHTML = captureHtml();
    if (phoneState.captureTags.length > 0) {
        phoneState.captureTags = [];
    }
    capture.hidden = false;
    ModeContext.pushModal(CAPTURE_MODAL);
    requireElement('phone-capture-tags').addEventListener('input', onCaptureTagsInput);
    requireElement('phone-capture-tags').addEventListener('keydown', onCaptureTagsKeyDown);
    requireElement('phone-capture-text').focus();
}

function closeCapture() {
    const capture = requireElement('phone-capture');
    capture.hidden = true;
    capture.innerHTML = '';
    ModeContext.removeModal(CAPTURE_MODAL);
}

async function saveCapture() {
    const text = requireElement('phone-capture-text').value.trim();
    if (text === '') {
        requireElement('phone-capture-text').focus();
        return;
    }
    addCaptureTag(requireElement('phone-capture-tags').value);
    const tags = phoneState.captureTags.length > 0 ? phoneState.captureTags.join(' ') : INBOX_TAG;
    const html = `<p>${text.split('\n').map((line) => escapeHtml(line)).join('<br>')}</p>`;
    closeCapture();
    await CommandGate.run('phone.capture', async () => {
        const note = await NotesAPI.createNote(null, '');
        await NotesAPI.saveNote(note.id, html, tags);
        await actionRefreshAndMaybeSelect({ context: 'phoneCapture' });
    });
}

function onCaptureTap(event) {
    const suggestion = event.target.closest('[data-capture-tag]');
    if (suggestion !== null) {
        addCaptureTag(suggestion.dataset.captureTag);
        requireElement('phone-capture-tags').value = '';
        requireElement('phone-capture').querySelector('.phone-capture-suggestions').innerHTML = '';
        requireElement('phone-capture-tags').focus();
        return;
    }
    if (event.target.closest('#phone-capture-cancel') !== null) {
        closeCapture();
        return;
    }
    if (event.target.closest('#phone-capture-save') !== null) {
        void saveCapture();
    }
}

// --- Setup -----------------------------------------------------------------------------

function installPhoneElements() {
    const row = document.querySelector('.search-input-row');
    const input = requireElement('search-input');
    const pills = document.createElement('div');
    pills.id = 'phone-search-pills';
    pills.className = 'phone-search-pills';
    row.insertBefore(pills, input);
    pills.addEventListener('click', onSearchPillsTap);
    input.addEventListener('focus', () => row.classList.remove('phone-search-has-pills'));
    input.addEventListener('blur', renderSearchPills);

    document.body.insertAdjacentHTML('beforeend', `
        <nav id="phone-bar" class="phone-bar" aria-label="Phone">
            <button type="button" id="phone-menu-button" class="phone-bar-button" aria-label="Menu">☰</button>
            <span id="phone-readonly" class="phone-readonly" hidden>👁 Read-only</span>
            <button type="button" id="phone-capture-button" class="phone-bar-capture" aria-label="Capture">+</button>
        </nav>
        <div id="phone-sheet-backdrop" class="phone-sheet-backdrop" hidden></div>
        <div id="phone-sheet" class="phone-sheet" role="menu" aria-label="View" hidden></div>
        <div id="phone-capture" class="phone-capture" role="dialog" aria-label="Capture" hidden></div>`);
    requireElement('phone-menu-button').addEventListener('click', openSheet);
    requireElement('phone-capture-button').addEventListener('click', openCapture);
    requireElement('phone-sheet-backdrop').addEventListener('click', closeSheet);
    requireElement('phone-sheet').addEventListener('click', onSheetTap);
    requireElement('phone-capture').addEventListener('click', onCaptureTap);

    for (const type of ['mousedown', 'click', 'dblclick']) {
        window.addEventListener(type, onNoteInteraction, { capture: true });
    }
    window.addEventListener('contextmenu', onContextMenu, { capture: true });
    window.addEventListener('popstate', onHistoryBack);
    new MutationObserver(keepNoteTagsShown).observe(requireElement('notes-container'), { childList: true, subtree: true });
    ModeContext.addListener((property) => {
        if (property === 'searchQuery') {
            onSearchQueryChanged();
        }
    });
    phoneState.historyQuery = input.value;
    window.history.replaceState({ phoneSearch: input.value }, '');
    phoneState.isInstalled = true;
}

function applyPhoneLayout(isPhoneWidth) {
    if (document.body.classList.contains(PHONE_CLASS) !== isPhoneWidth) {
        document.body.classList.toggle(PHONE_CLASS, isPhoneWidth);
    }
    renderSearchPills();
}

// Started by both ways the workspace starts: opening the page logged in (main.js) and
// logging in (auth.js).
export const PhoneMode = {
    init() {
        const media = window.matchMedia(PHONE_MEDIA_QUERY);
        if (!phoneState.isInstalled) {
            installPhoneElements();
        }
        applyPhoneLayout(media.matches);
        media.addEventListener('change', (event) => applyPhoneLayout(event.matches));
    },
};
