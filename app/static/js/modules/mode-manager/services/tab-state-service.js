import { ApplicationState } from '../../application-state.js';
import { HttpRequestError } from '../../expected-errors.js';
import { CONFIG } from '../../config.js';
import { ModeContextInstance as ModeContext } from '../mode-context.js';
import { ErrorHandler } from '../../error-handler.js';
import { areScrollAnchorsEqual, computeScrollAnchor } from './scroll-anchor-service.js';
import { CommandGate } from './command-gate-service.js';
import { buildSessionHeaders } from '../../session-auth.js';
import { AuthenticationRequiredError } from '../../client-state-api.js';
import { getReferenceViewsPayload, restoreReferenceNavigation } from './reference-source-navigation-service.js';
import { recordDateFiltersFromServer } from './date-range-filter-service.js';
import { recordFileFiltersFromServer } from './file-filter-service.js';
import { recordTreeShownFromServer } from './virtual-folders-state.js';
import { noticeOwnContextsChange } from './live-changes-service.js';
import { recordSearchLocks } from './edit-lock-service.js';

const HTTP_UNAUTHORIZED = 401;
const TAB_STATE_ENDPOINT = CONFIG.API.NOTES.TAB_STATE;
const TAB_STATE_NEW_TAB_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_NEW_TAB;
const TAB_STATE_DELETE_TAB_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_DELETE_TAB;
const TAB_STATE_SORT_MODE_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_SORT_MODE;
const TAB_STATE_DATE_FILTER_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_DATE_FILTER;
const TAB_STATE_FILE_FILTER_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_FILE_FILTER;
const TAB_STATE_UNTAGGED_VIEW_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_UNTAGGED_VIEW;
const TAB_STATE_SEARCH_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_SEARCH;
const TAB_STATE_SHOWN_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_SHOWN;
const TAB_STATE_MOVE_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_MOVE;
const TAB_STATE_SCROLL_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_SCROLL;
const TAB_STATE_REFERENCE_PAGE_ENDPOINT = CONFIG.API.NOTES.TAB_STATE_REFERENCE_PAGE;
const FOLDER_CONTEXT_ENDPOINT = CONFIG.API.VIRTUAL_FOLDERS.FOLDER_CONTEXT;
const TREE_SHOWN_ENDPOINT = CONFIG.API.VIRTUAL_FOLDERS.TREE_SHOWN;
const SCROLL_POLL_INTERVAL_MS = 1000;
const TAB_STATE_PERSIST_DEBOUNCE_MS = 300;

const moduleState = ApplicationState.createFields('tab-state-service', {
    lastPersistedScrollByTab: Object.create(null),

    scrollListenerAttached: false,
    pendingScrollFrame: null,
    lastScrollY: null,
    pendingTabId: null,
    scrollPollId: null,
    pendingPersistTimeout: null,
    pendingPersistRequest: null,
    // The search typed in each tab and not yet sent, newest only (sendPendingSearches).
    pendingSearchByTab: Object.create(null),
    pendingSearchRequest: null,
    // The tab the server holds as the one this view shows, from its last answer (sendShownTab).
    tabShownOnServer: null,
    // This view's scroll in each tab as the server last took or gave it (sendChangedScrolls).
    scrollSentByTab: Object.create(null),
    // What each reference page of this view shows, as the server last took or gave it
    // (sendChangedReferencePages).
    referencePageSentByTab: Object.create(null),
    // The page's own changes to the tabs (every request but a reading): how many were sent, how
    // many are unanswered, and, while any is, a promise for the moment none is (changeSent).
    changesSent: 0,
    changesUnanswered: 0,
    whenChangesAnswered: null,
    announceChangesAnswered: null,
    isScrollPersisting: false,
});


function setTabStateVersionFromServer(version) {
    const normalizedVersion = typeof version === 'number' ? version : 0;
    // The server can echo an unchanged tab-state version for no-op persistence responses.
    if (ModeContext.tabStateVersion !== normalizedVersion) {
        ModeContext.setTabStateVersion(normalizedVersion);
    }
}

export async function initializeTabStateService() {
    const serverState = await fetchTabState();
    ModeContext.hydrateTabState(serverState, { emitUpdate: false });
    restoreReferenceNavigation(serverState);
    setTabStateVersionFromServer(serverState.version);
    recordServerAnswer(serverState);
    // The scroll just loaded is the server's: nothing to send until the page scrolls.
    const loadedTabs = ModeContext.getTabStatePayload().tabs;
    for (const tabId of Object.keys(loadedTabs)) {
        moduleState.scrollSentByTab[tabId] = serializeScroll(loadedTabs[tabId]);
    }
    // So are its reference pages; one the page claims as it loads (a tab of note IDs no view's
    // record names) is not among them, and is sent with the first save.
    for (const tabId of Object.keys(serverState.referenceViews)) {
        moduleState.referencePageSentByTab[tabId] = serializeReferencePage(serverState.referenceViews[tabId]);
    }
    ModeContext.setTabStateUpdateHook(handleTabStateMutation);
    startScrollWatcher();
    startScrollPolling();
    return serverState;
}

// The server owns each tab's search (docs/future-plans/one-writer-refactoring.md, idea 1): the
// page asks for a search by name, one request at a time, and its copy of the tabs
// (persistTabStateSnapshot) carries no search the server takes. Text typed while a request is
// on its way replaces what waits, so the newest is what is sent last.
async function sendPendingSearches() {
    while (moduleState.pendingSearchRequest !== null) {
        await moduleState.pendingSearchRequest;
    }
    const waitingTabIds = Object.keys(moduleState.pendingSearchByTab);
    if (waitingTabIds.length === 0) {
        return;
    }
    const tabId = waitingTabIds[0];
    const searchQuery = moduleState.pendingSearchByTab[tabId];
    delete moduleState.pendingSearchByTab[tabId];
    moduleState.pendingSearchRequest = callTabStateApiAt(TAB_STATE_SEARCH_ENDPOINT, 'POST', { tabId, searchQuery })
        .then(takeServerAnswer)
        .finally(() => {
            moduleState.pendingSearchRequest = null;
        });
    await moduleState.pendingSearchRequest;
    await sendPendingSearches();
}

// The server owns the tab each view shows (docs/future-plans/one-writer-refactoring.md, idea 1):
// the page asks for it by name, before its copy of the tabs, which carries no shown tab the
// server takes. It goes as the snapshot writer's own request, so nothing else is sent meanwhile.
// A tab deleted elsewhere a moment ago is answered with the tab the server picked; the page
// hears of it with the contexts (adoptSharedSearchContexts) and asks no more.
async function sendShownTab() {
    moduleState.pendingPersistRequest = callTabStateApiAt(TAB_STATE_SHOWN_ENDPOINT, 'POST', { tabId: ModeContext.activeTabId })
        .then(takeServerAnswer)
        .finally(() => {
            moduleState.pendingPersistRequest = null;
        });
    await moduleState.pendingPersistRequest;
    while (moduleState.pendingPersistRequest !== null) {
        await moduleState.pendingPersistRequest;
    }
}

// The server owns the order of the tabs (docs/future-plans/one-writer-refactoring.md, idea 1): the
// page, having moved a tab in its own list, asks for that move by name, and its copy of the tabs
// carries no order the server takes, so a copy saved before this view heard of another view's move
// cannot undo it. It goes as the snapshot writer's own request, like the tab shown. Where the
// server's order then differs from this view's (another view moved or made a tab meanwhile), the
// view hears of it with the contexts (adoptSharedSearchContexts).
export async function moveTabOnServer(tabId, toTabId) {
    while (moduleState.pendingPersistRequest !== null) {
        await moduleState.pendingPersistRequest;
    }
    moduleState.pendingPersistRequest = callTabStateApiAt(TAB_STATE_MOVE_ENDPOINT, 'POST', { tabId, toTabId })
        .then(takeServerAnswer)
        .finally(() => {
            moduleState.pendingPersistRequest = null;
        });
    await moduleState.pendingPersistRequest;
}

function serializeScroll(tab) {
    return JSON.stringify([tab.scrollY, tab.anchorRootId, tab.scrollAnchor]);
}

// The server takes this view's scroll in a tab by name (docs/future-plans/one-writer-refactoring.md,
// idea 1): one request for each tab whose scroll changed since the last one sent, and the page's
// copy of the tabs carries no scroll the server takes. Each goes as the snapshot writer's own
// request, so never two at once, and names the version the page holds: a scroll measured before
// the tab's notes changed is not taken. A tab deleted elsewhere a moment ago is answered with
// nothing changed, and not asked again.
async function sendChangedScrolls() {
    for (const tabId of Object.keys(ModeContext.getTabStatePayload().tabs)) {
        while (moduleState.pendingPersistRequest !== null) {
            await moduleState.pendingPersistRequest;
        }
        // Read once nothing is on its way: the tab can be gone, or scrolled further, by now.
        const tabs = ModeContext.getTabStatePayload().tabs;
        if (!Object.prototype.hasOwnProperty.call(tabs, tabId)) {
            continue;
        }
        const scroll = serializeScroll(tabs[tabId]);
        if (moduleState.scrollSentByTab[tabId] === scroll) {
            continue;
        }
        const { scrollY, anchorRootId, scrollAnchor } = tabs[tabId];
        const sent = { tabId, scrollY, anchorRootId, scrollAnchor, version: ModeContext.tabStateVersion };
        moduleState.pendingPersistRequest = callTabStateApiAt(TAB_STATE_SCROLL_ENDPOINT, 'POST', sent)
            .then((state) => {
                takeServerAnswer(state);
                moduleState.scrollSentByTab[tabId] = scroll;
            })
            .finally(() => {
                moduleState.pendingPersistRequest = null;
            });
        await moduleState.pendingPersistRequest;
    }
    while (moduleState.pendingPersistRequest !== null) {
        await moduleState.pendingPersistRequest;
    }
}

function serializeReferencePage(page) {
    const scope = page.originScope;
    return JSON.stringify([
        page.fromTabId, page.referenceQuery, page.viewKind,
        scope.scopeTabId, scope.searchQuery, scope.sortMode, scope.isUntaggedView,
    ]);
}

// The server takes this view's reference pages by name (docs/future-plans/one-writer-refactoring.md,
// idea 1): one request for each page opened, each page showing something else, and each tab of
// note IDs the page took as one (adoptOrphanReferenceTabs), in the order they were opened, so a
// page is known before one opened from it. A page closed needs none: its tab is deleted by name,
// and another search in it ends it on the server too. Each goes as the snapshot writer's own
// request.
async function sendChangedReferencePages() {
    const pagesNow = getReferenceViewsPayload();
    for (const tabId of Object.keys(moduleState.referencePageSentByTab)) {
        if (!Object.prototype.hasOwnProperty.call(pagesNow, tabId)) {
            delete moduleState.referencePageSentByTab[tabId];
        }
    }
    for (const tabId of Object.keys(pagesNow)) {
        while (moduleState.pendingPersistRequest !== null) {
            await moduleState.pendingPersistRequest;
        }
        // Read once nothing is on its way: the page can be closed, or show something else, by now.
        const pages = getReferenceViewsPayload();
        if (!Object.prototype.hasOwnProperty.call(pages, tabId)) {
            continue;
        }
        const page = serializeReferencePage(pages[tabId]);
        if (moduleState.referencePageSentByTab[tabId] === page) {
            continue;
        }
        moduleState.pendingPersistRequest = callTabStateApiAt(TAB_STATE_REFERENCE_PAGE_ENDPOINT, 'POST', { tabId, ...pages[tabId] })
            .then((state) => {
                takeServerAnswer(state);
                moduleState.referencePageSentByTab[tabId] = page;
            })
            .finally(() => {
                moduleState.pendingPersistRequest = null;
            });
        await moduleState.pendingPersistRequest;
    }
    while (moduleState.pendingPersistRequest !== null) {
        await moduleState.pendingPersistRequest;
    }
}

// Everything the page keeps of its place in the tabs, sent to the server by name: the searches
// typed, the tab shown, the scroll in each tab and the reference pages. No copy of the tabs is
// sent: nothing is left for one to carry (docs/future-plans/one-writer-refactoring.md, idea 1).
export async function persistTabStateSnapshot() {
    // Searches go first, by name: every caller that saves before it reads the tabs again or
    // changes them finds the server holding what was typed. With none waiting, the copy is
    // sent without a pause, as before.
    if (moduleState.pendingSearchRequest !== null || Object.keys(moduleState.pendingSearchByTab).length > 0) {
        await sendPendingSearches();
    }
    // Tab actions and scroll polling share one snapshot writer. Read the
    // current payload only after the preceding response has updated its version.
    while (moduleState.pendingPersistRequest !== null) {
        await moduleState.pendingPersistRequest;
    }
    if (ModeContext.activeTabId !== moduleState.tabShownOnServer) {
        await sendShownTab();
    }
    await sendChangedScrolls();
    await sendChangedReferencePages();
}

function handleTabStateMutation(event) {
    if (!event || typeof event !== 'object') {
        throw new Error('tab-state mutation hook requires event object');
    }
    const reason = event.reason;
    if (reason !== 'searchQuery') {
        return;
    }
    const tabId = event.payload.activeTabId;
    const searchQuery = event.payload.tabs[tabId].searchQuery;
    // The same text can wait already: typed, replaced by the server's, and typed again.
    if (moduleState.pendingSearchByTab[tabId] !== searchQuery) {
        moduleState.pendingSearchByTab[tabId] = searchQuery;
    }
    scheduleTabStatePersist();
}

function scheduleTabStatePersist() {
    if (moduleState.pendingPersistTimeout !== null) {
        window.clearTimeout(moduleState.pendingPersistTimeout);
    }
    moduleState.pendingPersistTimeout = window.setTimeout(() => {
        moduleState.pendingPersistTimeout = null;
        void persistTabStateSnapshot();
    }, TAB_STATE_PERSIST_DEBOUNCE_MS);
}

function takeServerAnswer(state) {
    if (!state || typeof state !== 'object') {
        throw new Error('tab-state response missing payload');
    }
    setTabStateVersionFromServer(state.version);
    recordServerAnswer(state);
}

// Every answer carries the tabs' date range and Files filters, Untagged views and whether the
// folder tree shows, which only the server changes, and the tab it holds as shown here.
function recordServerAnswer(state) {
    recordDateFiltersFromServer(state);
    recordFileFiltersFromServer(state);
    recordTreeShownFromServer(state);
    ModeContext.recordUntaggedViewsFromServer(state);
    // Searches other views are typing (multi-view step 4).
    recordSearchLocks(state.searchLocks);
    if (moduleState.tabShownOnServer !== state.activeTabId) {
        moduleState.tabShownOnServer = state.activeTabId;
    }
}

// The server changed searches itself (Rename tag renamed a tag in them, rename_tag.py): the tabs take
// its state, and later snapshots are read at its version.
export async function reloadTabStateFromServer() {
    const serverState = await fetchTabStateNotOvertaken();
    // The view keeps its place when the tab shown stays; a page the server closed (its notes
    // deleted) gives way to its search, which brings its own.
    const keepsActiveTab = serverState.activeTabId === ModeContext.activeTabId;
    ModeContext.hydrateTabState(serverState, { preserveActiveRootTracking: keepsActiveTab });
    setTabStateVersionFromServer(serverState.version);
    recordServerAnswer(serverState);
    return serverState;
}

async function fetchTabState() {
    return await callTabStateApi('GET', null);
}

// The page takes the server's answers in order (docs/future-plans/one-writer-refactoring.md, idea
// 1; interaction principle 2: only the user's action changes the screen). A reading of the tabs is
// overtaken when a change of the page's own was sent while it was fetched, or when the page took a
// newer answer meanwhile: it may hold the tabs as they were before, and taking it would put the
// screen back (found 2026-11-15, the tab-switching suite: Untagged turned on while the tabs were
// read went off again). It is not taken; the tabs are read again once the page's changes are
// answered, so what another view changed still arrives. An older version alone is no sign: a
// restored backup's is, and nothing here is newer than it.
async function fetchTabStateNotOvertaken() {
    while (moduleState.whenChangesAnswered !== null) {
        await moduleState.whenChangesAnswered;
    }
    const changesSentBefore = moduleState.changesSent;
    const versionBefore = ModeContext.tabStateVersion;
    const serverState = await fetchTabState();
    const sentAChange = moduleState.changesSent !== changesSentBefore;
    const tookANewerAnswer = ModeContext.tabStateVersion > versionBefore
        && serverState.version < ModeContext.tabStateVersion;
    if (sentAChange || tookANewerAnswer) {
        return await fetchTabStateNotOvertaken();
    }
    return serverState;
}

function changeSent() {
    moduleState.changesSent += 1;
    moduleState.changesUnanswered += 1;
    if (moduleState.whenChangesAnswered === null) {
        moduleState.whenChangesAnswered = new Promise(resolve => {
            moduleState.announceChangesAnswered = resolve;
        });
    }
}

function changeAnswered() {
    moduleState.changesUnanswered -= 1;
    if (moduleState.changesUnanswered > 0) {
        return;
    }
    const announce = moduleState.announceChangesAnswered;
    moduleState.whenChangesAnswered = null;
    moduleState.announceChangesAnswered = null;
    announce();
}

async function callTabStateApi(method, body) {
    if (typeof body === 'undefined') {
        throw new Error('callTabStateApi requires body (use null)');
    }
    return await callTabStateApiAt(TAB_STATE_ENDPOINT, method, body);
}

async function callTabStateApiAt(endpoint, method, body) {
    if (typeof body === 'undefined') {
        throw new Error('callTabStateApiAt requires body (use null)');
    }
    if (typeof endpoint !== 'string' || endpoint.length === 0) {
        throw new Error('tab-state endpoint must be a non-empty string');
    }
    if (method === 'GET') {
        return await requestTabState(endpoint, method, body);
    }
    // Answered or failed, the change is no longer on its way (fetchTabStateNotOvertaken).
    changeSent();
    return await requestTabState(endpoint, method, body).finally(changeAnswered);
}

async function requestTabState(endpoint, method, body) {
    const response = await fetch(endpoint, {
        method,
        headers: buildSessionHeaders(true),
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
        ErrorHandler.handleApiError(null, response);
        // The session ended: handleApiError has shown the login screen.
        if (response.status === HTTP_UNAUTHORIZED) {
            throw new AuthenticationRequiredError(`tab-state ${method}: the session has ended`);
        }
        throw new HttpRequestError(`tab-state ${method} failed with status ${response.status}`);
    }
    const state = await response.json();
    // A change of this view's own to the shared contexts is not taken again (multi-view step 3),
    // and this browser's other tabs take it now.
    noticeOwnContextsChange(state.searchContextsRevision);
    return state;
}

/**
 * A new tab after copyFromTabId: with copiesView a duplicate of everything it shows (search,
 * sort, date range, Files filter, folder, Untagged view), without it a blank one.
 */
// isPage: a reference page, this view's own (multi-view editing step 2): no other view lists it.
export async function createTabOnServer(copyFromTabId, copiesView, isPage) {
    if (typeof copyFromTabId !== 'string' || copyFromTabId.length === 0) {
        throw new Error('copyFromTabId must be a non-empty string');
    }
    if (typeof copiesView !== 'boolean' || typeof isPage !== 'boolean') {
        throw new Error('createTabOnServer requires copiesView and isPage booleans');
    }
    const response = await callTabStateApiAt(TAB_STATE_NEW_TAB_ENDPOINT, 'POST', {
        copyFromTabId,
        copiesView,
        isPage,
        clientId: ModeContext.clientId,
    });
    takeServerAnswer(response);
    return response;
}

export async function deleteTabOnServer(tabId) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId must be a non-empty string');
    }
    const response = await callTabStateApiAt(TAB_STATE_DELETE_TAB_ENDPOINT, 'POST', { tabId });
    takeServerAnswer(response);
    return response;
}

/** A folder clicked in the tree ('' for `/`) in the search context tabId: its search, the one
 * before replaced; with adds (⌘-click), added or taken out, the rest of the search kept
 * (docs/ready-to-build/folders-tab-and-multiple-folders.md §2). The tab state answered. */
export async function chooseFolderOnServer(tabId, folder, adds) {
    if (typeof tabId !== 'string' || tabId.length === 0 || typeof folder !== 'string' || typeof adds !== 'boolean') {
        throw new Error('chooseFolderOnServer requires the search context, the folder and whether it adds');
    }
    const response = await callTabStateApiAt(FOLDER_CONTEXT_ENDPOINT, 'POST', {
        tabId,
        folder,
        adds,
        clientId: ModeContext.clientId,
        undoContext: captureUndoContext(),
    });
    takeServerAnswer(response);
    return response;
}

/** The folders tab: the tree shown or hidden, no search context changed. The tab state answered. */
export async function setTreeShownOnServer(isShown) {
    if (typeof isShown !== 'boolean') {
        throw new Error('setTreeShownOnServer requires whether the tree shows');
    }
    const response = await callTabStateApiAt(TREE_SHOWN_ENDPOINT, 'POST', { isShown });
    takeServerAnswer(response);
    return response;
}

function captureUndoContext() {
    const tabId = ModeContext.activeTabId;
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('ModeContext.activeTabId must be a non-empty string');
    }
    const epoch = ModeContext.undoContextEpoch;
    if (!Number.isInteger(epoch) || epoch < 0) {
        throw new Error('ModeContext.undoContextEpoch must be a non-negative integer');
    }
    const searchQuery = ModeContext.searchQuery;
    if (searchQuery !== null && typeof searchQuery !== 'string') {
        throw new Error('ModeContext.searchQuery must be a string or null');
    }
    if (searchQuery === null) {
        return `tab:${tabId}|search:|epoch:${epoch}`;
    }
    return `tab:${tabId}|search:${searchQuery}|epoch:${epoch}`;
}

export async function setTabSortModeOnServer(tabId, sortMode) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId must be a non-empty string');
    }
    if (typeof sortMode !== 'string' || sortMode.length === 0) {
        throw new Error('sortMode must be a non-empty string');
    }
    const response = await callTabStateApiAt(TAB_STATE_SORT_MODE_ENDPOINT, 'POST', {
        tabId,
        sortMode,
        clientId: ModeContext.clientId,
        undoContext: captureUndoContext(),
    });
    takeServerAnswer(response);
    return response;
}

/** Set a tab's date range filter ({ field, rangeKind, fromDate, toDate }; rangeKind 'none' clears it). */
export async function setTabDateFilterOnServer(tabId, filter) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId must be a non-empty string');
    }
    if (!filter || typeof filter !== 'object') {
        throw new Error('setTabDateFilterOnServer requires a filter object');
    }
    const response = await callTabStateApiAt(TAB_STATE_DATE_FILTER_ENDPOINT, 'POST', {
        tabId,
        field: filter.field,
        rangeKind: filter.rangeKind,
        fromDate: filter.fromDate,
        toDate: filter.toDate,
        clientId: ModeContext.clientId,
        undoContext: captureUndoContext(),
    });
    takeServerAnswer(response);
    return response;
}

/** Set (kind 'none': clear) a tab's Files filter (file-filter-service.js). */
export async function setTabFileFilterOnServer(tabId, kind) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId must be a non-empty string');
    }
    if (typeof kind !== 'string' || kind.length === 0) {
        throw new Error('setTabFileFilterOnServer requires a kind');
    }
    const response = await callTabStateApiAt(TAB_STATE_FILE_FILTER_ENDPOINT, 'POST', {
        tabId,
        kind,
        clientId: ModeContext.clientId,
        undoContext: captureUndoContext(),
    });
    takeServerAnswer(response);
    return response;
}

export async function setTabUntaggedViewOnServer(tabId, isUntaggedView) {
    if (typeof tabId !== 'string' || tabId.length === 0) {
        throw new Error('tabId must be a non-empty string');
    }
    if (typeof isUntaggedView !== 'boolean') {
        throw new Error('setTabUntaggedViewOnServer requires isUntaggedView boolean');
    }
    const response = await callTabStateApiAt(TAB_STATE_UNTAGGED_VIEW_ENDPOINT, 'POST', {
        tabId,
        isUntaggedView,
        clientId: ModeContext.clientId,
        undoContext: captureUndoContext(),
    });
    takeServerAnswer(response);
    return response;
}

function startScrollWatcher() {
    if (moduleState.scrollListenerAttached) {
        return;
    }
    moduleState.lastScrollY = getCurrentScrollY();
    window.addEventListener('scroll', handleScrollEvent, { passive: true });
    moduleState.scrollListenerAttached = true;
}

function handleScrollEvent() {
    if (ModeContext.shouldIgnoreScrollEvents()) {
        return;
    }
    if (ModeContext.isLoading) {
        return;
    }
    if (moduleState.pendingScrollFrame !== null) {
        return;
    }
    const sourceTabId = ModeContext.activeTabId;
    moduleState.pendingTabId = sourceTabId;
    moduleState.pendingScrollFrame = window.requestAnimationFrame(() => {
        moduleState.pendingScrollFrame = null;
        const current = getCurrentScrollY();
        if (current !== moduleState.lastScrollY) {
            moduleState.lastScrollY = current;
            const effectiveTabId = moduleState.pendingTabId === null ? ModeContext.activeTabId : moduleState.pendingTabId;  // shockharness: ignore[DEF002] reason="null means no tab switch is pending"
            // A programmatic restore can update ModeContext before the browser scroll event lands.
            if (ModeContext.getTabScrollPosition(effectiveTabId) !== current) {
                ModeContext.updateTabScroll(effectiveTabId, current, { emit: true });
            }
        }
        moduleState.pendingTabId = null;
    });
}

function startScrollPolling() {
    if (moduleState.scrollPollId !== null) {
        return;
    }
    moduleState.scrollPollId = window.setInterval(pollPersistScroll, SCROLL_POLL_INTERVAL_MS);
}

async function pollPersistScroll() {
    if (moduleState.isScrollPersisting) {
        return;
    }
    if (document.hidden) {
        return;
    }
    if (CommandGate.isBusy()) {
        return;
    }
    if (ModeContext.shouldIgnoreScrollEvents()) {
        return;
    }
    if (ModeContext.isLoading) {
        return;
    }
    moduleState.isScrollPersisting = true;
    // The session can end while a save is in flight (it expired, a backup
    // restore or a password change ended it): the login screen already shows,
    // and the last moment's scroll is not saved. Every other failure surfaces.
    await persistCurrentScroll().catch((error) => { // shockharness: ignore[EXC002] reason="a session that ended is shown as the login screen; the last moment's scroll is dropped on purpose"
        if (!(error instanceof AuthenticationRequiredError)) {
            throw error;
        }
    }).finally(() => {
        moduleState.isScrollPersisting = false;
    });
}

async function persistCurrentScroll() {
    const tabId = ModeContext.activeTabId;
    const current = getCurrentScrollY();
    const previous = moduleState.lastPersistedScrollByTab[tabId];
    if (typeof previous === 'number' && previous === current) {
        return;
    }
    // Scroll polling can hit the same Y after another scroll listener already stored it.
    if (ModeContext.getTabScrollPosition(tabId) !== current) {
        ModeContext.updateActiveTabScroll(current);
    }
    const nextScrollAnchor = computeScrollAnchor({ anchorBias: 'auto' });
    // Polling can run when the view has no root notes, so computed and stored anchors are both null.
    if (!areScrollAnchorsEqual(ModeContext.getTabScrollAnchor(tabId), nextScrollAnchor)) {
        ModeContext.updateActiveTabScrollAnchor(nextScrollAnchor);
    }
    await persistTabStateSnapshot();
    moduleState.lastPersistedScrollByTab[tabId] = current;
}

function getCurrentScrollY() {
    return Math.max(0, Math.round(window.scrollY));
}

