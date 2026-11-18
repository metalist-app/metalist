import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { ApplicationState } from '../../app/static/js/modules/application-state.js';

class HttpRequestError extends Error {}
class AuthenticationRequiredError extends HttpRequestError {}

async function harness() {
    const source = readFileSync(new URL(
        '../../app/static/js/modules/mode-manager/services/tab-state-service.js', import.meta.url,
    ), 'utf8').replace(/^import[\s\S]*?from '[^']+';\s*/gm, '').replace(/^export /gm, '');
    const requests = [];
    const polls = [];
    const apiErrors = [];
    const restoredReferenceTabs = [];
    const hooks = [];
    // Readings of the tabs held back by a test (holdReads), and the states the page took.
    const reads = [];
    const taken = [];
    let holdsReads = false;
    let timers = 0;
    let serverVersion = 1;
    // The tab the server holds as shown: only a request to show one changes it.
    let serverShown = 'first';
    // The reference pages the page holds (reference-source-navigation-service.js), by their tab.
    const referencePages = {};
    const payload = {
        activeTabId: 'first', tabOrder: ['first', 'second'], version: 1,
        tabs: { first: { scrollY: 0, scrollAnchor: null }, second: { scrollY: 0, scrollAnchor: null } },
    };
    const context = {
        activeTabId: 'first', tabStateVersion: 0, isLoading: false,
        undoContextEpoch: 0, searchQuery: null, clientId: 'this-page',
        hydrateTabState(state) { taken.push(state); }, setTabStateUpdateHook(hook) { hooks.push(hook); }, recordUntaggedViewsFromServer() {},
        setTabStateVersion(version) { this.tabStateVersion = version; payload.version = version; },
        getTabStatePayload: () => structuredClone(payload),
        shouldIgnoreScrollEvents: () => false,
        getTabScrollPosition: id => payload.tabs[id].scrollY,
        updateActiveTabScroll(y) { payload.tabs[this.activeTabId].scrollY = y; },
        getTabScrollAnchor: id => payload.tabs[id].scrollAnchor,
        updateActiveTabScrollAnchor(anchor) { payload.tabs[this.activeTabId].scrollAnchor = anchor; },
    };
    const window = {
        scrollY: 0, addEventListener() {},
        setInterval(callback) { polls.push(callback); return polls.length; },
        setTimeout() { timers += 1; return timers; }, clearTimeout() {},
    };
    const dependencies = {
        ApplicationState, ModeContext: context, window, document: { hidden: false },
        CONFIG: { API: { NOTES: { TAB_STATE: '/tabs', TAB_STATE_SEARCH: '/tabs/search', TAB_STATE_SHOWN: '/tabs/shown', TAB_STATE_MOVE: '/tabs/move', TAB_STATE_SCROLL: '/tabs/scroll', TAB_STATE_REFERENCE_PAGE: '/tabs/reference-page', TAB_STATE_UNTAGGED_VIEW: '/tabs/untagged' }, VIRTUAL_FOLDERS: { FOLDER_CONTEXT: '/folder-context', TREE_SHOWN: '/tree-shown' } } },
        CommandGate: { isBusy: () => false }, buildSessionHeaders: () => ({}),
        computeScrollAnchor: () => null, areScrollAnchorsEqual: (a, b) => a === b,
        restoreReferenceNavigation: (state) => restoredReferenceTabs.push(state.tabs),
        getReferenceViewsPayload: () => structuredClone(referencePages),
        recordDateFiltersFromServer: () => {},
        recordFileFiltersFromServer: () => {},
        recordTreeShownFromServer: () => {},
        noticeOwnContextsChange: () => {},
        recordSearchLocks: () => {},
        ErrorHandler: { handleApiError(_error, response) { apiErrors.push(response.status); } },
        HttpRequestError, AuthenticationRequiredError,
        fetch: async (endpoint, options) => {
            if (options.method === 'GET' && holdsReads) {
                return await new Promise(resolve => reads.push({
                    answer: version => resolve({ ok: true, json: async () => ({ ...structuredClone(payload), referenceViews: {}, version }) }),
                }));
            }
            if (options.method === 'GET') return { ok: true, json: async () => ({ ...structuredClone(payload), referenceViews: {} }) };
            const sent = JSON.parse(options.body);
            // A change asked for by name is answered with the tabs, as every tab-state request is.
            const answered = endpoint === '/tabs' ? sent : structuredClone(payload);
            if (endpoint === '/tabs/shown') serverShown = sent.tabId;
            const shownWhenAsked = serverShown;
            return await new Promise((resolve, reject) => requests.push({
                endpoint, sent, reject,
                complete: () => resolve({ ok: true, json: async () => ({ ...answered, referenceViews: {}, activeTabId: shownWhenAsked, version: ++serverVersion }) }),
                answer: status => resolve({ ok: false, status, json: async () => ({ detail: 'refused' }) }),
            }));
        },
    };
    const service = new Function(...Object.keys(dependencies), `${source}
        return { initializeTabStateService, persistTabStateSnapshot, moveTabOnServer, reloadTabStateFromServer, setTabUntaggedViewOnServer };`)(...Object.values(dependencies));
    await service.initializeTabStateService();
    assert.equal(polls.length, 1);
    // Reference views are restored from the freshly loaded server tab state.
    assert.deepEqual(restoredReferenceTabs, [payload.tabs]);
    // What ModeContext tells the service when the search of the tab shown changes.
    const typeSearch = (text) => {
        payload.tabs[payload.activeTabId].searchQuery = text;
        hooks[0]({ reason: 'searchQuery', payload: structuredClone(payload) });
    };
    taken.length = 0;
    // The page shows another tab: ModeContext and the copy it would save both say so.
    const showTab = (tabId) => { context.activeTabId = tabId; payload.activeTabId = tabId; };
    // Answers every request, and those each answer leads to, until none is left unanswered.
    let answered = 0;
    const answerAll = async () => {
        await new Promise(setImmediate);
        while (answered < requests.length) {
            requests[answered].complete();
            answered += 1;
            await new Promise(setImmediate);
        }
    };
    const holdReads = () => { holdsReads = true; };
    // The page moves a tab in its own list, as a drag does (ModeContext.moveTabToHoveredSlot).
    const moveTab = (order) => { payload.tabOrder = order; };
    return { referencePages, moveTab, service, requests, context, payload, window, poll: polls[0], apiErrors, typeSearch, reads, taken, holdReads, showTab, answerAll };
}

const settle = () => new Promise(setImmediate);

test('scroll polls cannot overlap a slow save and write the same tab position twice', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    const second = h.poll();
    // Observe both promises even on the old implementation, which rejects the second save.
    const settled = Promise.allSettled([first, second]);
    const requestCount = h.requests.length;
    for (const request of h.requests) request.complete();
    const results = await settled;
    assert.deepEqual(results.map(result => result.status), ['fulfilled', 'fulfilled']);
    assert.equal(requestCount, 1);
    await h.poll();
    assert.equal(h.requests.length, 1);
});

test('scroll changed during a slow save is persisted by the following poll', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    h.window.scrollY = 250;
    const skipped = h.poll();
    const settled = Promise.allSettled([first, skipped]);
    for (const request of h.requests) request.complete();
    assert.deepEqual((await settled).map(result => result.status), ['fulfilled', 'fulfilled']);
    assert.equal(h.requests.length, 1);
    const next = h.poll();
    assert.deepEqual([h.requests[1].endpoint, h.requests[1].sent.scrollY], ['/tabs/scroll', 250]);
    h.requests[1].complete();
    await next;
});

test('a failed scroll save surfaces its error and releases the next poll', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    const failure = new Error('Connection reset');
    const rejected = assert.rejects(first, error => error === failure);
    h.requests[0].reject(failure);
    await rejected;
    const next = h.poll();
    assert.equal(h.requests.length, 2);
    h.requests[1].complete();
    await next;
});

test('a tab switch during a pending scroll save preserves each tabs position', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    h.context.activeTabId = 'second';
    h.payload.activeTabId = 'second';
    h.window.scrollY = 300;
    await h.answerAll();
    await first;
    const second = h.poll();
    await h.answerAll();
    await second;
    // The first tab's scroll went by name; then the tab now shown, then its own scroll.
    const byName = h.requests.filter(request => request.endpoint !== '/tabs');
    assert.deepEqual(byName.map(request => [request.endpoint, request.sent.tabId, request.sent.scrollY]), [
        ['/tabs/scroll', 'first', 100],
        ['/tabs/shown', 'second', undefined],
        ['/tabs/scroll', 'second', 300],
    ]);
});

test('snapshot persistence waits for an active scroll save and avoids a duplicate request', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const poll = h.poll();
    const explicitSave = h.service.persistTabStateSnapshot();
    const requestCount = h.requests.length;
    const settled = Promise.allSettled([poll, explicitSave]);
    for (const request of h.requests) request.complete();
    const results = await settled;
    assert.deepEqual(results.map(result => result.status), ['fulfilled', 'fulfilled']);
    assert.equal(requestCount, 1);
});

test('a search typed is asked for by name, before the scroll in its tab', async () => {
    const h = await harness();
    h.typeSearch('groceries');
    h.payload.tabs.first.scrollY = 100;
    const saved = h.service.persistTabStateSnapshot();
    await new Promise(setImmediate);
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/search']);
    assert.deepEqual(h.requests[0].sent, { tabId: 'first', searchQuery: 'groceries' });
    h.requests[0].complete();
    await new Promise(setImmediate);
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/search', '/tabs/scroll']);
    h.requests[1].complete();
    await saved;
});

test('more typed while a search is on its way is sent after it, newest only', async () => {
    const h = await harness();
    h.typeSearch('gro');
    const saved = h.service.persistTabStateSnapshot();
    await new Promise(setImmediate);
    h.typeSearch('groce');
    h.typeSearch('groceries');
    h.requests[0].complete();
    await new Promise(setImmediate);
    assert.deepEqual(h.requests.map(request => request.sent.searchQuery), ['gro', 'groceries']);
    h.requests[1].complete();
    await saved;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/search', '/tabs/search']);
});

test('the same search typed again while it waits is sent once', async () => {
    const h = await harness();
    h.typeSearch('groceries');
    h.typeSearch('groceries');
    const saved = h.service.persistTabStateSnapshot();
    await new Promise(setImmediate);
    h.requests[0].complete();
    await saved;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/search']);
});

test('a search typed in one tab is still sent after another tab is shown', async () => {
    const h = await harness();
    h.typeSearch('groceries');
    h.showTab('second');
    h.typeSearch('plants');
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.map(request => [request.endpoint, request.sent]).slice(0, 3), [
        ['/tabs/search', { tabId: 'first', searchQuery: 'groceries' }],
        ['/tabs/search', { tabId: 'second', searchQuery: 'plants' }],
        ['/tabs/shown', { tabId: 'second' }],
    ]);
});

test('a save waiting behind another sends what the page holds once its turn comes', async () => {
    const h = await harness();
    h.payload.tabs.first.scrollY = 100;
    const first = h.service.persistTabStateSnapshot();
    const next = h.service.persistTabStateSnapshot();
    h.payload.tabs.first.scrollY = 250;
    await h.answerAll();
    await Promise.all([first, next]);
    assert.deepEqual(h.requests.map(request => [request.endpoint, request.sent.scrollY, request.sent.version]), [
        ['/tabs/scroll', 100, 1], ['/tabs/scroll', 250, 2],
    ]);
});

test('a scroll save that finds the session ended shows the login screen and is dropped quietly', async () => {
    // The session can end while a save is in flight (it expired, a backup
    // restore or a password change ended it): the 401 shows the login screen,
    // and the last moment's scroll is not saved; it is no crash.
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    h.requests[0].answer(401);
    await first;
    assert.deepEqual(h.apiErrors, [401]);
    // Not recorded as saved: the next poll sends it again.
    const next = h.poll();
    assert.equal(h.requests.length, 2);
    assert.deepEqual([h.requests[1].endpoint, h.requests[1].sent.scrollY], ['/tabs/scroll', 100]);
    h.requests[1].complete();
    await next;
});

test('a scroll save refused for another reason still surfaces its error', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const first = h.poll();
    const rejected = assert.rejects(first, error => error instanceof HttpRequestError && !(error instanceof AuthenticationRequiredError));
    h.requests[0].answer(500);
    await rejected;
    assert.deepEqual(h.apiErrors, [500]);
});

// The page applies the server's answers in order (docs/future-plans/one-writer-refactoring.md,
// idea 1; cases agreed 2026-11-17). A reading of the tabs asked before a change of the page's own
// is older than that change: taking it would put the screen back.
const VERSION_BEFORE = 1;
const VERSION_AFTER = 2;
const VERSION_LATER = 3;

test('a reading with nothing changed meanwhile is taken as it is', async () => {
    const h = await harness();
    h.holdReads();
    const reading = h.service.reloadTabStateFromServer();
    await settle();
    h.reads[0].answer(VERSION_BEFORE);
    await reading;
    assert.equal(h.reads.length, 1);
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_BEFORE]);
});

test('a reading answered after a change of the page is not taken, and is asked again', async () => {
    const h = await harness();
    h.holdReads();
    const reading = h.service.reloadTabStateFromServer();
    await settle();
    const change = h.service.setTabUntaggedViewOnServer('first', true);
    await settle();
    h.requests[0].complete();
    await change;
    assert.equal(h.context.tabStateVersion, VERSION_AFTER);
    h.reads[0].answer(VERSION_BEFORE);
    await settle();
    assert.deepEqual(h.taken, [], 'the older reading is not taken');
    assert.equal(h.reads.length, 2, 'the tabs are asked for again');
    h.reads[1].answer(VERSION_AFTER);
    await reading;
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_AFTER]);
    assert.equal(h.context.tabStateVersion, VERSION_AFTER);
});

test('a reading answered while a change of the page is on its way waits for the change', async () => {
    const h = await harness();
    h.holdReads();
    const reading = h.service.reloadTabStateFromServer();
    await settle();
    const change = h.service.setTabUntaggedViewOnServer('first', true);
    await settle();
    h.reads[0].answer(VERSION_BEFORE);
    await settle();
    assert.deepEqual(h.taken, [], 'the reading asked before the change is not taken');
    assert.equal(h.reads.length, 1, 'and is asked again only once the change is answered');
    h.requests[0].complete();
    await change;
    await settle();
    assert.equal(h.reads.length, 2);
    h.reads[1].answer(VERSION_AFTER);
    await reading;
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_AFTER]);
});

test('a reading asked while a change of the page is on its way is sent after its answer', async () => {
    const h = await harness();
    h.holdReads();
    const change = h.service.setTabUntaggedViewOnServer('first', true);
    await settle();
    const reading = h.service.reloadTabStateFromServer();
    await settle();
    assert.equal(h.reads.length, 0);
    h.requests[0].complete();
    await change;
    await settle();
    assert.equal(h.reads.length, 1);
    h.reads[0].answer(VERSION_AFTER);
    await reading;
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_AFTER]);
});

test('of two readings, the older answered last is not taken over the newer', async () => {
    const h = await harness();
    h.holdReads();
    const older = h.service.reloadTabStateFromServer();
    const newer = h.service.reloadTabStateFromServer();
    await settle();
    h.reads[1].answer(VERSION_LATER);
    await newer;
    h.reads[0].answer(VERSION_AFTER);
    await settle();
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_LATER]);
    assert.equal(h.reads.length, 3);
    h.reads[2].answer(VERSION_LATER);
    await older;
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_LATER, VERSION_LATER]);
});

test('a reading from a server whose version went back is taken: nothing here is newer', async () => {
    // A restored backup holds an earlier version; the page took no answer meanwhile.
    const h = await harness();
    h.context.setTabStateVersion(VERSION_LATER);
    h.holdReads();
    const reading = h.service.reloadTabStateFromServer();
    await settle();
    h.reads[0].answer(VERSION_BEFORE);
    await reading;
    assert.equal(h.reads.length, 1);
    assert.deepEqual(h.taken.map(state => state.version), [VERSION_BEFORE]);
});

// The server owns the tab each view shows (idea 1; cases agreed 2026-11-17): the page asks for it
// by name, and sends no copy of its tabs.
test('a tab shown is asked for by name, and no copy of the tabs follows', async () => {
    const h = await harness();
    h.showTab('second');
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/shown']);
    assert.deepEqual(h.requests[0].sent, { tabId: 'second' });
});

test('a tab shown and left again before the save is not asked for', async () => {
    const h = await harness();
    h.showTab('second');
    h.showTab('first');
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.filter(request => request.endpoint === '/tabs/shown'), []);
});

test('the tab shown when the save is sent is the one asked for', async () => {
    // Case 2: A, B, A while an earlier save is on its way.
    const h = await harness();
    h.window.scrollY = 100;
    const earlier = h.poll();
    h.showTab('second');
    const switched = h.service.persistTabStateSnapshot();
    h.showTab('first');
    await h.answerAll();
    await Promise.all([earlier, switched]);
    assert.deepEqual(h.requests.filter(request => request.endpoint === '/tabs/shown'), []);
});

test('the tab shown is asked for once, not again with every save', async () => {
    const h = await harness();
    h.showTab('second');
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    h.payload.tabs.second.scrollY = 100;
    const next = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await next;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/shown', '/tabs/scroll']);
});

// The server owns the order of the tabs (idea 1; cases agreed 2026-11-17): the page asks for a
// move by name, and sends no copy of its tabs.
test('a tab moved is asked for by name, once, and no copy of the tabs follows', async () => {
    const h = await harness();
    h.moveTab(['second', 'first']);
    const moved = h.service.moveTabOnServer('first', 'second').then(() => h.service.persistTabStateSnapshot());
    await h.answerAll();
    await moved;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/move']);
    assert.deepEqual(h.requests[0].sent, { tabId: 'first', toTabId: 'second' });
});

test('a tab moved with the page scrolled is asked for before the scroll', async () => {
    const h = await harness();
    h.moveTab(['second', 'first']);
    const moved = h.service.moveTabOnServer('first', 'second');
    h.payload.tabs.first.scrollY = 100;
    const saved = moved.then(() => h.service.persistTabStateSnapshot());
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/move', '/tabs/scroll']);
});

test('a move waits for a save on its way, so the two are never sent together', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const earlier = h.poll();
    h.moveTab(['second', 'first']);
    const moved = h.service.moveTabOnServer('first', 'second');
    await settle();
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/scroll']);
    await h.answerAll();
    await Promise.all([earlier, moved]);
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/scroll', '/tabs/move']);
});

// The server takes this view's scroll in a tab by name (idea 1; cases agreed 2026-11-17), and the
// page's copy of the tabs carries no scroll the server takes.
test('a scroll is asked for by name, with the version the page holds, and no copy follows', async () => {
    const h = await harness();
    h.window.scrollY = 100;
    const polled = h.poll();
    await h.answerAll();
    await polled;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/scroll']);
    assert.deepEqual([h.requests[0].sent.tabId, h.requests[0].sent.scrollY, h.requests[0].sent.version], ['first', 100, 1]);
});

test('a scroll that has not changed since it was sent is not sent again', async () => {
    // Case 7.
    const h = await harness();
    h.window.scrollY = 100;
    const polled = h.poll();
    await h.answerAll();
    await polled;
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.equal(h.requests.length, 1);
});

test('a page that has not scrolled since it loaded sends no scroll', async () => {
    const h = await harness();
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.filter(request => request.endpoint === '/tabs/scroll'), []);
});

test('the scroll of a tab left is sent for that tab, after the tab now shown', async () => {
    // Case 2: the page records the scroll of the tab it leaves, then shows the other.
    const h = await harness();
    h.payload.tabs.first.scrollY = 100;
    h.showTab('second');
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.map(request => [request.endpoint, request.sent.tabId]), [
        ['/tabs/shown', 'second'], ['/tabs/scroll', 'first'],
    ]);
});

// The server takes this view's reference pages by name (idea 1; cases agreed 2026-11-18), and
// the page sends no copy of the tabs at all.
const recipePage = () => ({
    fromTabId: 'first', referenceQuery: 'recipe-note', viewKind: 'source',
    originScope: { scopeTabId: 'first', searchQuery: '', sortMode: 'normal', isUntaggedView: false },
});

test('a reference page opened is asked for by name, once', async () => {
    const h = await harness();
    h.referencePages.second = recipePage();
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    const again = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await again;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/reference-page']);
    assert.deepEqual(h.requests[0].sent, { tabId: 'second', ...recipePage() });
});

test('a reference page that shows something else is asked for again', async () => {
    // Case 6: a later AI reference replaces the AI references a page shows.
    const h = await harness();
    h.referencePages.second = { ...recipePage(), referenceQuery: 'two-notes', viewKind: 'references' };
    const opened = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await opened;
    h.referencePages.second = { ...recipePage(), referenceQuery: 'menu-note', viewKind: 'reference' };
    const replaced = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await replaced;
    assert.deepEqual(h.requests.map(request => [request.endpoint, request.sent.referenceQuery, request.sent.viewKind]), [
        ['/tabs/reference-page', 'two-notes', 'references'], ['/tabs/reference-page', 'menu-note', 'reference'],
    ]);
});

test('a reference page closed asks for nothing, and one opened in its tab again is asked for', async () => {
    const h = await harness();
    h.referencePages.second = recipePage();
    const opened = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await opened;
    delete h.referencePages.second;
    const closed = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await closed;
    assert.equal(h.requests.length, 1);
    h.referencePages.second = recipePage();
    const reopened = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await reopened;
    assert.deepEqual(h.requests.map(request => request.endpoint), ['/tabs/reference-page', '/tabs/reference-page']);
});

test('pages are asked for in the order they were opened, after the tab shown and its scroll', async () => {
    const h = await harness();
    h.referencePages.first = { ...recipePage(), fromTabId: 'second' };
    h.referencePages.second = recipePage();
    h.showTab('second');
    h.payload.tabs.second.scrollY = 100;
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.map(request => [request.endpoint, request.sent.tabId]), [
        ['/tabs/shown', 'second'], ['/tabs/scroll', 'second'],
        ['/tabs/reference-page', 'first'], ['/tabs/reference-page', 'second'],
    ]);
});

test('saving sends no copy of the tabs, whatever the page holds', async () => {
    const h = await harness();
    h.typeSearch('groceries');
    h.showTab('second');
    h.payload.tabs.second.scrollY = 100;
    h.moveTab(['second', 'first']);
    h.referencePages.second = recipePage();
    const saved = h.service.persistTabStateSnapshot();
    await h.answerAll();
    await saved;
    assert.deepEqual(h.requests.filter(request => request.endpoint === '/tabs'), []);
});
