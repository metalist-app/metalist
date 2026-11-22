import { ApplicationState } from '../../app/static/js/modules/application-state.js';
import { MS_PER_SECOND } from '../../app/static/js/modules/time-units.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// The server records every notes.view response as the tab's warm view. A tab
// switch must therefore never let an in-flight response go unapplied.
function extractFunction(source, name) {
    const start = source.search(new RegExp(`(export )?(async )?function ${name}\\(`));
    assert.ok(start >= 0, `missing function ${name}`);
    const rest = source.slice(start + 1);
    const next = rest.search(/\n(export )?(async )?function /);
    return source.slice(start, next < 0 ? undefined : start + 1 + next).replace(/^export /, '');
}

// The module's named numbers (const NAME = ...;), so extracted functions see them.
const namedConstants = (source) => source.match(/^const [A-Z][A-Z0-9_]* = [^;\n]+;$/gm).join('\n');
const uiSource = readFileSync(new URL(
    '../../app/static/js/modules/mode-manager/actions/ui-actions.js', import.meta.url,
), 'utf8');
const uiNamedConstants = namedConstants(uiSource);
const keyboardSource = readFileSync(new URL(
    '../../app/static/js/modules/mode-manager/events/keyboard-events.js', import.meta.url,
), 'utf8');

function deferred() {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
}

function buildHarness() {
    const events = [];
    const heldFetch = deferred();
    let fetchCount = 0;
    const snapshot = () => ({ diffOps: [], notes: {}, rootIds: [], rootCountTotal: 1, searchRootCountTotal: 1, rootWindowStart: 0, rootBandMargin: 75, pagesClosedAtVersion: 0 });
    const ModeContext = {
        activeTabId: 'A', tabOrder: ['A', 'B'], isEditing: false, isUntaggedView: false,
        activeTabSortMode: 'normal', currentNoteId: null, isInitialPageLoad: false,
        knownRootCount: 1, noteCount: 1,
        getExecutedSearchQuery: () => '', getRootAnchorId: () => null, getLastKnownRootId: () => null,
        getVisibleRootRange: () => ({ topRootId: null, bottomRootId: null }), setRootWindow() {},
        getTabNoteHashCount: () => 1, tabs: { A: { anchorRootId: null }, B: { anchorRootId: null } },
        getNoteHashPayload: () => ({}), syncNoteHashesFromSnapshot() {}, syncRootIds() {},
        getRootCountTotals: () => ({ rootCountTotal: 1, searchRootCountTotal: 1 }),
        setRootCountTotals() {}, hasNoteHash: () => false,
        beginIgnoreScrollEvents() {}, endIgnoreScrollEvents() {}, restoreScrollForActiveTab() {},
        resetTabDiffCache() {},
        switchToTab(tabId) { events.push(`switch:${tabId}`); this.activeTabId = tabId; },
        restoreScrollForActiveTabNow() { events.push(`scroll-now:${this.activeTabId}`); },
    };
    const uiDependencies = {
        MS_PER_SECOND,
        setSearchHighlightPhrases() {},
        // No reference pages closed with their notes in these views.
        noticeClosedReferencePages() {},
        recordNotesShown() {},
        recordEditedRootMovedElsewhere() {},
        recordLockedRoots() {},
        // No note is edited in a floating window here (editing-surface.js).
        isEditingInWindow: () => false, markNoteEditedInWindow() {},
        noticeRefusedEdit() {},
        tellOtherTabsWhatIsEdited() {},
        ModeContext,
        moduleState: ApplicationState.createFields(`test.tab-switch.${Math.random()}`, { viewRequestInFlight: false }),
        Logger: { logAction() {}, logDebug() {}, logNoop() {} },
        NotesAPI: {
            async fetchView(_noteId, _search, tabId) {
                fetchCount += 1;
                events.push(`fetch:${tabId}`);
                if (fetchCount === 1) await heldFetch.promise;
                return { snapshot: snapshot() };
            },
        },
        CONFIG: { DEBUG: { LOG_API_CALLS: false }, EDITOR: { DEFAULT_CURSOR_POSITION: 'START' } },
        document: { querySelector: () => null },
        window: { setTimeout },
        performance,
        console: { log() {} },
        applyDifferentialView() {
            events.push(`apply:${ModeContext.activeTabId}`);
            return { notesContainer: {}, editingNoteElement: null };
        },
        resetInfiniteScrollState() {}, syncTagBar() {}, clearTagBar() {}, detachEditorSurface() {},
        attachEditorSurface() {}, clearEditingStateForHiddenFilteredNote() {},
        initializeEditSessionCollapseStateFromNoteElement() {},
        DOMUtils: { getNoteContentHTML: () => '', getNoteContent: () => ({}), setNoteEditable() {}, revealCaret() {}, focusNoteEdge() {} },
        updateSearchResultsCount() {}, updateRootSortIndicator() {}, updateDateRangeIndicator() {}, updateFileFilterIndicator() {}, async updateVirtualFolders() {}, updateUntaggedViewIndicator() {}, updateReferenceSourceIndicator() {},
        rebuildRootDateSeparators() {}, rebuildFileSizePills() {}, async refreshBacklinksPanel() {},
        captureViewportRoot: () => null, holdViewportRoot() {},
        measureVisibleRootRange: () => null,
    };
    const uiFunctionNames = ['actionRefreshAndMaybeSelect'];
    if (/function resolveVisibleRootRange\(/.test(uiSource)) uiFunctionNames.push('resolveVisibleRootRange');
    if (/function waitForViewRequestIdle\(/.test(uiSource)) uiFunctionNames.push('waitForViewRequestIdle');
    uiFunctionNames.push('holdViewRequestsWhile');
    const uiActions = new Function(
        ...Object.keys(uiDependencies),
        `${uiNamedConstants}\n${uiFunctionNames.map((name) => extractFunction(uiSource, name)).join('\n')}\nreturn { ${uiFunctionNames.join(', ')} };`,
    )(...Object.values(uiDependencies));

    const switchFunctionNames = ['switchToTabContext'];
    if (/function settleViewRequestsBeforeTabChange\(/.test(keyboardSource)) {
        switchFunctionNames.push('settleViewRequestsBeforeTabChange');
    }
    const switchSource = switchFunctionNames.map((name) => extractFunction(keyboardSource, name)).join('\n')
        .replaceAll("await import('../actions/ui-actions.js')", 'await loadUiActions()');
    const switchDependencies = {
        ModeContext, performance,
        loadUiActions: async () => uiActions,
        isViewingReferenceSource: () => false,
        async actionSaveAndExitEditingWithoutRefreshing() {},
        clearCachedNotesDomForTab() {}, clearActiveNotesDom() {},
        async persistCurrentTabState() {}, async persistTabStateSnapshot() {},
        cacheNotesDomForTab(tabId) { events.push(`cache:${tabId}`); },
        restoreNotesDomForTab(tabId) { events.push(`restore:${tabId}`); return { restored: true, moved: 1 }; },
        syncSearchInputField() {}, showFolderOfActiveContext() {}, isReferenceViewTransitionPending: () => false, updateSearchContextsList() {}, closeOpenSearchQuote() {},
    };
    const switchToTabContext = new Function(
        ...Object.keys(switchDependencies), `${switchSource}\nreturn switchToTabContext;`,
    )(...Object.values(switchDependencies));
    return { events, heldFetch, uiActions: { ...uiActions, ModeContext }, switchToTabContext };
}

test('tab switch applies an in-flight view response to its own tab before caching that tab', async () => {
    const { events, heldFetch, uiActions, switchToTabContext } = buildHarness();

    const pendingRefresh = uiActions.actionRefreshAndMaybeSelect({ context: 'infinite-scroll' });
    const pendingSwitch = switchToTabContext('B', {});
    await new Promise((resolve) => setTimeout(resolve, 50));
    heldFetch.resolve();
    await Promise.all([pendingRefresh, pendingSwitch]);

    assert.ok(events.includes('apply:A'), `tab A response was not applied: ${events.join(' ')}`);
    assert.ok(events.indexOf('apply:A') < events.indexOf('cache:A'), `tab A cached before its response applied: ${events.join(' ')}`);
    assert.ok(events.indexOf('apply:A') < events.indexOf('switch:B'));
});

test('tab switch positions the restored DOM before waiting on any refresh', async () => {
    const { events, heldFetch, switchToTabContext } = buildHarness();
    heldFetch.resolve();
    await switchToTabContext('B', {});

    const restoreIndex = events.indexOf('restore:B');
    assert.ok(restoreIndex >= 0, events.join(' '));
    assert.equal(events[restoreIndex + 1], 'scroll-now:B', events.join(' '));
    assert.ok(events.indexOf('scroll-now:B') < events.indexOf('fetch:B'), events.join(' '));
});

// A tab change that asks the server before it switches (a reference page closed with its notes, a
// search context changed elsewhere): a view request asked for meanwhile waits, and is made for the
// tab shown after. It went out for the old tab and came back to another: "notes.view response for
// tab A arrived after the active tab changed to B" (GitHub, Firefox, 2026-11-22).
test('a view request asked for while the tabs are read from the server waits for the tab change', async () => {
    const { events, heldFetch, uiActions } = buildHarness();
    heldFetch.resolve();
    const serverAnswer = deferred();

    const pendingChange = uiActions.holdViewRequestsWhile(async () => {
        await serverAnswer.promise;
        events.push('switch:B');
        uiActions.ModeContext.activeTabId = 'B';
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const pendingRefresh = uiActions.actionRefreshAndMaybeSelect({ context: 'infinite-scroll' });
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.deepEqual(events, [], 'nothing is fetched while the tabs are read');
    serverAnswer.resolve();
    await Promise.all([pendingChange, pendingRefresh]);

    assert.deepEqual(events.slice(0, 3), ['switch:B', 'fetch:B', 'apply:B']);
});
