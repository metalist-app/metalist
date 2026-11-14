import { NOT_FOUND } from '../../not-found.js';
import { ApplicationState } from '../../application-state.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { isReferenceViewTransitionPending } from './reference-view-transition-service.js';

// The kinds of temporary view: a note's source, the notes referencing it, or an AI
// answer's references (one of them, or all of them).
const REFERENCE_VIEW_KINDS = new Set(['source', 'backlinks', 'reference', 'references']);
// The views an AI answer opens; a later AI reference replaces any of them.
export const AI_REFERENCE_VIEW_KINDS = new Set(['reference', 'references']);
// Each kind of page, as its search context's row names it (`miscellaneous > Source note`) and the
// header tells screen readers.
const LABEL_BY_VIEW_KIND = Object.freeze({
    source: 'Source note',
    backlinks: 'Backlinks',
    reference: 'Reference',
    references: 'All references',
});

// On the header's arrows, shown in place of the search input (main.css).
const CHIP_SHOWN_CLASS = 'is-shown';
// An arrow with nowhere to go is hidden in its place, so the others never move (the maintainer,
// 2026-11-13: only the arrows that can act show, as undo and redo do).
const ARROW_UNAVAILABLE_CLASS = 'is-unavailable';
// ⏮ shows from the second page on; on the first, ◀ already goes back to the search.
const FIRST_PAGE_DEPTH = 1;

// Reference tabs are ordinary server tabs whose search is a hidden note-ID query.
// Which tabs are reference views, and where each was opened from, is kept with
// the tabs on the server (tab state's referenceViews), so every window and reload
// labels them. Windows from before that kept it in their own sessionStorage under
// this key; it moves to the server once and is removed.
const REFERENCE_NAVIGATION_STORAGE_KEY = 'metalist_reference_navigation_stack';
// A search made only of note IDs, one or joined by OR, is a reference view's.
const NOTE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const NOTE_ID_SEPARATOR = /\s+OR\s+/;

const moduleState = ApplicationState.createFields('reference-source-navigation-service', {
    referenceNavigationStack: [],
    hasRestoredFromSession: false,
    // Reference pages gone back from, to go forward to again (docs/ready-to-build/reference-cards.md,
    // "Reference pages", §2), by search context: { referenceQuery, viewKind, scrollY }, the next
    // one forward last. Each context keeps its own while MetaList is open (2026-11-14); a reload, or
    // following another reference, drops them.
    forwardPagesByContext: new Map(),
});

function requireForwardPage(page) {
    if (!page || typeof page !== 'object') {
        throw new Error('A forward reference page must be an object');
    }
    if (typeof page.referenceQuery !== 'string' || page.referenceQuery === '') {
        throw new Error('A forward reference page needs its referenceQuery');
    }
    requireReferenceViewKind(page.viewKind);
    if (!Number.isFinite(page.scrollY) || page.scrollY < 0) {
        throw new Error('A forward reference page needs where it was scrolled');
    }
}

function requireContextTabId(contextTabId) {
    if (typeof contextTabId !== 'string' || contextTabId === '') {
        throw new Error('The way forward belongs to a search context: its tab id is required');
    }
}

function forwardPagesOf(contextTabId) {
    requireContextTabId(contextTabId);
    if (!moduleState.forwardPagesByContext.has(contextTabId)) {
        return [];
    }
    return moduleState.forwardPagesByContext.get(contextTabId);
}

/** Remember pages gone back from in a search context, the nearest (the next one forward) last. */
export function pushForwardReferencePages(contextTabId, pages) {
    requireContextTabId(contextTabId);
    if (!Array.isArray(pages)) {
        throw new Error('pushForwardReferencePages requires a list');
    }
    pages.forEach(requireForwardPage);
    if (pages.length === 0) {
        return;
    }
    const kept = forwardPagesOf(contextTabId);
    moduleState.forwardPagesByContext.set(contextTabId, [...kept, ...pages.map((page) => ({ ...page }))]);
    updateReferenceSourceIndicator();
}

/** The context's next page forward, taken off its way forward, or null when there is none. */
export function popForwardReferencePage(contextTabId) {
    const kept = forwardPagesOf(contextTabId);
    if (kept.length === 0) {
        return null;
    }
    const page = kept[kept.length - 1];
    if (kept.length === 1) {
        moduleState.forwardPagesByContext.delete(contextTabId);
    } else {
        moduleState.forwardPagesByContext.set(contextTabId, kept.slice(0, -1));
    }
    updateReferenceSourceIndicator();
    return page;
}

/** Following another reference, or leaving for the search, drops the context's way forward. */
export function clearForwardReferencePages(contextTabId) {
    if (forwardPagesOf(contextTabId).length === 0) {
        return;
    }
    moduleState.forwardPagesByContext.delete(contextTabId);
    updateReferenceSourceIndicator();
}

export function hasForwardReferencePage(contextTabId) {
    return forwardPagesOf(contextTabId).length > 0;
}

/** The search context the user is in: the one a shown reference page was opened from, or the tab. */
export function getActiveSearchContextTabId() {
    if (isViewingReferenceSource()) {
        return getActiveReferenceOriginScope().scopeTabId;
    }
    return ModeContext.activeTabId;
}

/** The stack's entries opened from a search context, in the order they were opened. */
function entriesFromContext(contextTabId) {
    requireContextTabId(contextTabId);
    pruneReferenceNavigationStackToExistingTabs();
    return moduleState.referenceNavigationStack.filter((entry) => entry.originScope.scopeTabId === contextTabId);
}

/**
 * The reference page a search context was last on: the deepest page of the newest way from it, or
 * '' when it shows its search. Choosing the context goes back there (2026-11-14). Tabs saved before
 * then can hold older ways from the same context too; they close when it goes back to its search.
 */
export function getReferencePageTabForContext(contextTabId) {
    const fromContext = entriesFromContext(contextTabId);
    const deepest = fromContext.filter(
        (entry) => !fromContext.some((other) => other.fromTabId === entry.toTabId),
    );
    if (deepest.length === 0) {
        return '';
    }
    // The stack keeps the order pages were opened in: the last deepest page is the newest way's.
    return deepest[deepest.length - 1].toTabId;
}

/** Every reference page opened from a search context, the newest first: closing it closes them. */
export function getReferencePageTabsForContext(contextTabId) {
    return entriesFromContext(contextTabId).map((entry) => entry.toTabId).reverse();
}

/** "Source note", "Backlinks"…: the kind of page a search context is on, or '' on its search. */
export function getReferencePageLabelForContext(contextTabId) {
    const pageTabId = getReferencePageTabForContext(contextTabId);
    if (pageTabId === '') {
        return '';
    }
    return getReferenceNavigationLabelForTab(pageTabId);
}

function requireReferenceViewKind(viewKind) {
    if (!REFERENCE_VIEW_KINDS.has(viewKind)) {
        throw new Error('Reference navigation requires a source, backlinks or references viewKind');
    }
}


function copyOriginScope(originScope) {
    if (!originScope || typeof originScope !== 'object' || Array.isArray(originScope)) {
        throw new Error('Reference navigation requires originScope');
    }
    for (const key of ['scopeTabId', 'sortMode']) {
        if (typeof originScope[key] !== 'string' || originScope[key].length === 0) {
            throw new Error(`Reference origin scope missing ${key}`);
        }
    }
    if (typeof originScope.searchQuery !== 'string') {
        throw new Error('Reference origin scope missing searchQuery');
    }
    if (typeof originScope.isUntaggedView !== 'boolean') {
        throw new Error('Reference origin scope missing isUntaggedView');
    }
    return {
        scopeTabId: originScope.scopeTabId,
        searchQuery: originScope.searchQuery,
        sortMode: originScope.sortMode,
        isUntaggedView: originScope.isUntaggedView,
    };
}

function copyReferenceNavigationEntry(entry) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        throw new Error('Reference navigation stack entry must be an object');
    }
    for (const key of ['fromTabId', 'toTabId', 'referenceQuery']) {
        if (typeof entry[key] !== 'string' || entry[key].length === 0) {
            throw new Error(`Reference navigation stack entry missing ${key}`);
        }
    }
    requireReferenceViewKind(entry.viewKind);
    return {
        fromTabId: entry.fromTabId,
        toTabId: entry.toTabId,
        referenceQuery: entry.referenceQuery,
        originScope: copyOriginScope(entry.originScope),
        viewKind: entry.viewKind,
    };
}

export function parseStoredReferenceNavigationStack(rawValue) {
    if (rawValue === null) {
        return [];
    }
    if (typeof rawValue !== 'string') {
        throw new Error('Stored reference navigation must be a string');
    }
    const parsed = JSON.parse(rawValue);
    if (!Array.isArray(parsed)) {
        throw new Error('Stored reference navigation must be a list');
    }
    // Only kinds of view this version knows are restored; others (e.g. the removed
    // similar-notes view, docs/design/similar-notes-learnings.md) are dropped, leaving
    // their tab as an ordinary tab.
    return parsed
        .filter((entry) => entry && typeof entry === 'object' && REFERENCE_VIEW_KINDS.has(entry.viewKind))
        .map(copyReferenceNavigationEntry);
}

function noteIdsOfReferenceQuery(searchQuery) {
    const terms = searchQuery.trim().split(NOTE_ID_SEPARATOR);
    if (!terms.every((term) => NOTE_ID_PATTERN.test(term))) {
        return [];
    }
    return terms;
}

function hasReferenceNavigationEntryForTab(tabId) {
    return moduleState.referenceNavigationStack.some((entry) => entry.toTabId === tabId);
}

function isUnclaimedReferenceTab(tabId) {
    return !hasReferenceNavigationEntryForTab(tabId)
        && noteIdsOfReferenceQuery(ModeContext.tabs[tabId].searchQuery).length > 0;
}

/** The nearest tab to adopt an unclaimed page: before it, else after it; never another unclaimed one. */
function findAdoptingTab(tabOrder, index) {
    for (let before = index - 1; before >= 0; before -= 1) {
        if (!isUnclaimedReferenceTab(tabOrder[before])) return tabOrder[before];
    }
    for (let after = index + 1; after < tabOrder.length; after += 1) {
        if (!isUnclaimedReferenceTab(tabOrder[after])) return tabOrder[after];
    }
    return '';
}

/** A page adopted by a page goes on its way, so belongs to its search context; else to the tab. */
function originScopeOfAdoptingTab(fromTabId) {
    const fromIndex = findReferenceNavigationEntryIndexForTab(fromTabId);
    if (fromIndex !== NOT_FOUND) {
        return copyOriginScope(moduleState.referenceNavigationStack[fromIndex].originScope);
    }
    return copyOriginScope({
        scopeTabId: fromTabId,
        searchQuery: ModeContext.tabs[fromTabId].searchQuery,
        sortMode: ModeContext.getTabSortMode(fromTabId),
        isUntaggedView: false,
    });
}

/**
 * A tab whose search is only note IDs but that no reference view claims (its
 * window's record was lost, or the tab it came from was closed, as 0.29.0 left it)
 * becomes one again, opened from the nearest tab before it, so no tab is ever named by
 * an ID; ◀ goes there. Opened from a page, it goes on that page's way, so it belongs to
 * that page's search context; a page is never a search context. With no other tab it
 * stays as it is.
 */
function adoptOrphanReferenceTabs() {
    const tabOrder = ModeContext.tabOrder;
    for (let i = 0; i < tabOrder.length; i += 1) {
        const tabId = tabOrder[i];
        if (!isUnclaimedReferenceTab(tabId)) continue;
        const fromTabId = findAdoptingTab(tabOrder, i);
        if (fromTabId === '') continue;
        const searchQuery = ModeContext.tabs[tabId].searchQuery;
        moduleState.referenceNavigationStack.push({
            fromTabId,
            toTabId: tabId,
            referenceQuery: searchQuery,
            originScope: originScopeOfAdoptingTab(fromTabId),
            viewKind: noteIdsOfReferenceQuery(searchQuery).length === 1 ? 'source' : 'references',
        });
    }
}

/**
 * Restore reference views when the server tab state loads: the server's, plus any
 * this window kept in sessionStorage before they moved to the server.
 *
 * Keeps only entries whose tabs still exist and whose reference tab still runs the
 * exact hidden query; any other search means the user already left that view.
 */
export function restoreReferenceNavigation(serverState) {
    if (moduleState.hasRestoredFromSession) {
        throw new Error('Reference navigation can be restored only once per page load');
    }
    if (!serverState || typeof serverState !== 'object') {
        throw new Error('Reference navigation restore requires the server tab state');
    }
    const serverTabs = serverState.tabs;
    const serverViews = serverState.referenceViews;
    if (!serverTabs || typeof serverTabs !== 'object' || Array.isArray(serverTabs)) {
        throw new Error('Reference navigation restore requires server tabs');
    }
    if (!serverViews || typeof serverViews !== 'object' || Array.isArray(serverViews)) {
        throw new Error('Reference navigation restore requires server referenceViews');
    }
    if (moduleState.referenceNavigationStack.length !== 0) {
        throw new Error('Reference navigation restore requires an empty in-memory stack');
    }
    moduleState.hasRestoredFromSession = true;
    const candidates = Object.entries(serverViews)
        .map(([toTabId, view]) => copyReferenceNavigationEntry({ ...view, toTabId }));
    const storedValue = sessionStorage.getItem(REFERENCE_NAVIGATION_STORAGE_KEY);
    for (const entry of parseStoredReferenceNavigationStack(storedValue)) {
        if (!candidates.some((candidate) => candidate.toTabId === entry.toTabId)) {
            candidates.push(entry);
        }
    }
    if (storedValue !== null) {
        sessionStorage.removeItem(REFERENCE_NAVIGATION_STORAGE_KEY);
    }
    for (const entry of candidates) {
        const fromTab = serverTabs[entry.fromTabId];
        const toTab = serverTabs[entry.toTabId];
        if (fromTab === undefined || toTab === undefined) continue;
        if (toTab.searchQuery !== entry.referenceQuery) continue;
        // 0.29.0 left a view open when the search context it came from was closed; it is adopted
        // below, like a page no view claims, so it belongs to a search context that is there.
        if (serverTabs[entry.originScope.scopeTabId] === undefined) continue;
        moduleState.referenceNavigationStack.push(entry);
    }
    adoptOrphanReferenceTabs();
    updateReferenceSourceIndicator();
}

/** The reference views, by the tab showing them, as tab state sends them to the server. */
export function getReferenceViewsPayload() {
    pruneReferenceNavigationStackToExistingTabs();
    const views = {};
    for (const entry of moduleState.referenceNavigationStack) {
        views[entry.toTabId] = {
            fromTabId: entry.fromTabId,
            referenceQuery: entry.referenceQuery,
            viewKind: entry.viewKind,
            originScope: copyOriginScope(entry.originScope),
        };
    }
    return views;
}

function pruneReferenceNavigationStackToExistingTabs() {
    const tabOrder = ModeContext.tabOrder;
    if (!Array.isArray(tabOrder)) {
        throw new Error('ModeContext.tabOrder must be an array');
    }
    const existingTabIds = new Set(tabOrder);
    let writeIndex = 0;
    for (let i = 0; i < moduleState.referenceNavigationStack.length; i += 1) {
        const entry = moduleState.referenceNavigationStack[i];
        if (!entry || typeof entry !== 'object') {
            throw new Error('Reference navigation stack entry must be an object');
        }
        if (typeof entry.fromTabId !== 'string' || entry.fromTabId.length === 0) {
            throw new Error('Reference navigation stack entry missing fromTabId');
        }
        if (typeof entry.toTabId !== 'string' || entry.toTabId.length === 0) {
            throw new Error('Reference navigation stack entry missing toTabId');
        }
        if (!existingTabIds.has(entry.fromTabId) || !existingTabIds.has(entry.toTabId)) {
            continue;
        }
        if (writeIndex !== i) moduleState.referenceNavigationStack[writeIndex] = entry;
        writeIndex += 1;
    }
    if (writeIndex < moduleState.referenceNavigationStack.length) {
        moduleState.referenceNavigationStack.length = writeIndex;
        // A view whose origin tab closed is adopted by the tab before it.
        adoptOrphanReferenceTabs();
    }
}

function findReferenceNavigationEntryIndexForActiveTab() {
    return findReferenceNavigationEntryIndexForTab(ModeContext.activeTabId);
}


function findReferenceNavigationEntryIndexForTab(tabId) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('Reference navigation lookup requires tabId');
    }
    for (let i = moduleState.referenceNavigationStack.length - 1; i >= 0; i -= 1) {
        if (moduleState.referenceNavigationStack[i].toTabId === tabId) {
            return i;
        }
    }
    return NOT_FOUND;
}

export function isViewingReferenceSource() {
    pruneReferenceNavigationStackToExistingTabs();
    return findReferenceNavigationEntryIndexForActiveTab() !== NOT_FOUND;
}


/**
 * Return the temporary view label for a server tab, or an empty string for an
 * ordinary user search. Internal exact-note queries must never become tab labels
 * or search-history entries.
 */
export function getReferenceNavigationLabelForTab(tabId) {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForTab(tabId);
    if (entryIndex === NOT_FOUND) return '';
    return LABEL_BY_VIEW_KIND[moduleState.referenceNavigationStack[entryIndex].viewKind];
}

/** The kind of reference view a server tab shows, or '' for an ordinary search. */
export function getReferenceViewKindForTab(tabId) {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForTab(tabId);
    if (entryIndex === NOT_FOUND) return '';
    return moduleState.referenceNavigationStack[entryIndex].viewKind;
}

export function getActiveReferenceViewKind() {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        throw new Error('Active tab is not a reference view');
    }
    return moduleState.referenceNavigationStack[entryIndex].viewKind;
}

/**
 * The stack entries leading from the original search to the active reference view,
 * the first one opened from the search and the last one the active view's.
 */
export function getActiveReferenceChain() {
    pruneReferenceNavigationStackToExistingTabs();
    let entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        throw new Error('Active tab is not a reference view');
    }
    const chain = [];
    while (entryIndex !== NOT_FOUND) {
        const entry = moduleState.referenceNavigationStack[entryIndex];
        if (chain.some((chained) => chained.toTabId === entry.toTabId)) {
            throw new Error('Reference navigation stack forms a cycle');
        }
        chain.unshift(entry);
        entryIndex = findReferenceNavigationEntryIndexForTab(entry.fromTabId);
    }
    return chain;
}

export function getActiveReferenceSourceQuery() {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        return '';
    }
    const entry = moduleState.referenceNavigationStack[entryIndex];
    if (typeof entry.referenceQuery !== 'string' || entry.referenceQuery.length === 0) {
        throw new Error('Reference navigation entry missing referenceQuery');
    }
    return entry.referenceQuery;
}

export function getActiveReferenceOriginScope() {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        throw new Error('Active tab is not a reference source');
    }
    return copyOriginScope(moduleState.referenceNavigationStack[entryIndex].originScope);
}

export function captureReferenceOriginScopeForActiveTab() {
    if (isViewingReferenceSource()) {
        return getActiveReferenceOriginScope();
    }
    const scopeTabId = ModeContext.activeTabId;
    if (typeof scopeTabId !== 'string' || scopeTabId.length === 0) {
        throw new Error('Reference origin requires active tab id');
    }
    return copyOriginScope({
        scopeTabId,
        searchQuery: ModeContext.getExecutedSearchQuery(scopeTabId),
        sortMode: ModeContext.getTabSortMode(scopeTabId),
        isUntaggedView: ModeContext.isUntaggedView,
    });
}

function requireChipElement(id) {
    const element = document.getElementById(id);
    if (!(element instanceof HTMLElement)) {
        throw new Error(`${id} element missing`);
    }
    return element;
}

function showArrowWhenAvailable(button, isAvailable) {
    button.classList.toggle(ARROW_UNAVAILABLE_CLASS, !isAvailable);
    button.setAttribute('aria-hidden', isAvailable ? 'false' : 'true');
    button.tabIndex = isAvailable ? 0 : -1;
}

function renderReferenceViewChip() {
    const chip = requireChipElement('reference-source-indicator');
    const label = requireChipElement('reference-source-indicator-label');
    const forwardButton = requireChipElement('reference-view-chip-forward');
    const searchButton = requireChipElement('reference-source-indicator-clear');
    if (!isViewingReferenceSource()) {
        chip.classList.remove(CHIP_SHOWN_CLASS);
        return;
    }
    const chain = getActiveReferenceChain();
    const entry = chain[chain.length - 1];
    // Unseen between the arrows (main.css), for screen readers.
    label.textContent = LABEL_BY_VIEW_KIND[entry.viewKind];
    // ◀ at every level: from the first page it goes back to the search. ⏮ only when it goes
    // further than ◀ would.
    showArrowWhenAvailable(searchButton, chain.length > FIRST_PAGE_DEPTH);
    // ▶ only after going back: forward along the way just come back.
    showArrowWhenAvailable(forwardButton, hasForwardReferencePage(entry.originScope.scopeTabId));
    chip.classList.toggle(CHIP_SHOWN_CLASS, true);
}

/**
 * Show the active tab's reference view, if any, in the search bar: the chip with
 * its label and back arrow in place of the search input. While a reference
 * navigation is pending the bar keeps showing the view the user left.
 */
export function updateReferenceSourceIndicator() {
    if (isReferenceViewTransitionPending()) {
        return;
    }
    renderReferenceViewChip();
}

export function pushReferenceNavigationEntry(
    fromTabId,
    toTabId,
    referenceQuery,
    originScope,
    viewKind,
) {
    requireReferenceViewKind(viewKind);
    if (typeof fromTabId !== 'string' || fromTabId.length === 0) {
        throw new Error('pushReferenceNavigationEntry requires fromTabId');
    }
    if (typeof toTabId !== 'string' || toTabId.length === 0) {
        throw new Error('pushReferenceNavigationEntry requires toTabId');
    }
    if (typeof referenceQuery !== 'string' || referenceQuery.length === 0) {
        throw new Error('pushReferenceNavigationEntry requires referenceQuery');
    }
    if (hasReferenceNavigationEntryForTab(toTabId)) {
        throw new Error('A tab can show only one reference view');
    }
    moduleState.referenceNavigationStack.push({
        fromTabId,
        toTabId,
        referenceQuery,
        originScope: copyOriginScope(originScope),
        viewKind,
    });
    updateReferenceSourceIndicator();
}

export function replaceActiveReferenceNavigationQuery(referenceQuery, viewKind) {
    requireReferenceViewKind(viewKind);
    if (typeof referenceQuery !== 'string' || referenceQuery.length === 0) {
        throw new Error('replaceActiveReferenceNavigationQuery requires referenceQuery');
    }
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        throw new Error('Cannot replace reference query outside reference source mode');
    }
    const entry = moduleState.referenceNavigationStack[entryIndex];
    moduleState.referenceNavigationStack[entryIndex] = {
        ...entry,
        referenceQuery,
        viewKind,
    };
    updateReferenceSourceIndicator();
}

export function popReferenceNavigationEntryForActiveTab() {
    pruneReferenceNavigationStackToExistingTabs();
    const entryIndex = findReferenceNavigationEntryIndexForActiveTab();
    if (entryIndex === NOT_FOUND) {
        updateReferenceSourceIndicator();
        return null;
    }
    const [entry] = moduleState.referenceNavigationStack.splice(entryIndex, 1);
    if (!entry || typeof entry !== 'object') {
        throw new Error('Reference navigation stack entry must be an object');
    }
    updateReferenceSourceIndicator();
    return entry;
}

/**
 * Leave every reference view between the active one and the original search:
 * removes their entries and returns them, the one opened from the search first.
 */
export function popActiveReferenceChain() {
    const chain = getActiveReferenceChain();
    const chainTabIds = new Set(chain.map((entry) => entry.toTabId));
    const stack = moduleState.referenceNavigationStack;
    let writeIndex = 0;
    for (let i = 0; i < stack.length; i += 1) {
        const entry = stack[i];
        if (chainTabIds.has(entry.toTabId)) continue;
        if (writeIndex !== i) stack[writeIndex] = entry;
        writeIndex += 1;
    }
    stack.length = writeIndex;
    updateReferenceSourceIndicator();
    return chain;
}

/**
 * The tab of the level on the active reference path (the view shown now included) that
 * shows this reference, or '' when none does. Following a reference already open on the
 * path goes back to it instead of opening a tab (docs/ui/references.md, Reference views).
 */
export function findReferenceLevelOnActivePath(referenceQuery, viewKind) {
    requireReferenceViewKind(viewKind);
    if (typeof referenceQuery !== 'string' || referenceQuery.length === 0) {
        throw new Error('findReferenceLevelOnActivePath requires referenceQuery');
    }
    if (!isViewingReferenceSource()) {
        return '';
    }
    for (const entry of getActiveReferenceChain()) {
        if (entry.referenceQuery === referenceQuery && entry.viewKind === viewKind) {
            return entry.toTabId;
        }
    }
    return '';
}

/**
 * Leave the levels of the active reference path after the one shown in levelTabId:
 * removes their entries and returns them, the one shown now first.
 */
export function popReferenceLevelsAbove(levelTabId) {
    const chain = getActiveReferenceChain();
    const levelIndex = chain.findIndex((entry) => entry.toTabId === levelTabId);
    if (levelIndex === NOT_FOUND) {
        throw new Error(`Tab ${levelTabId} is not on the active reference path`);
    }
    const leftTabIds = new Set(chain.slice(levelIndex + 1).map((entry) => entry.toTabId));
    const left = [];
    const stack = moduleState.referenceNavigationStack;
    let writeIndex = 0;
    for (let i = 0; i < stack.length; i += 1) {
        const entry = stack[i];
        if (leftTabIds.has(entry.toTabId)) {
            left.unshift(entry);
            continue;
        }
        if (writeIndex !== i) stack[writeIndex] = entry;
        writeIndex += 1;
    }
    stack.length = writeIndex;
    updateReferenceSourceIndicator();
    return left;
}

export function dismissReferenceSourceModeForActiveTab() {
    return popReferenceNavigationEntryForActiveTab() !== null;
}
