import assert from 'node:assert/strict';
import test from 'node:test';


function createStorage() {
    const entries = new Map();
    return {
        getItem: (key) => entries.has(key) ? entries.get(key) : null,
        setItem: (key, value) => entries.set(key, String(value)),
        removeItem: (key) => entries.delete(key),
    };
}


globalThis.sessionStorage = createStorage();
globalThis.localStorage = createStorage();
globalThis.window = {};

const {
    SearchSuggestionStatisticsModal,
} = await import('../../app/static/js/modules/modals/search-suggestion-statistics-modal.js');


function installModalStateHarness(modal, initialState) {
    let state = { ...initialState };
    let renderCount = 0;
    modal.getModalState = () => state;
    modal.updateModalState = (updates) => {
        state = { ...state, ...updates };
    };
    modal.renderModalContent = () => {
        renderCount += 1;
    };
    modal.isOpen = true;
    return {
        getState: () => state,
        getRenderCount: () => renderCount,
    };
}


function createStatisticsModal(overrides) {
    assert.equal(typeof overrides, 'object');
    const callbacks = {
        loadStatistics: async () => ({ retentionPopulatedDayLimit: 365, days: [] }),
        readWindows: () => [1, 7, 30],
        readShowWindowLabels: () => true,
        readLimitNoteCredits: () => true,
        saveSettings: async () => {},
        resetStatistics: async () => true,
        ...overrides,
    };
    return new SearchSuggestionStatisticsModal(
        callbacks.loadStatistics,
        callbacks.readWindows,
        callbacks.readShowWindowLabels,
        callbacks.readLimitNoteCredits,
        callbacks.saveSettings,
        callbacks.resetStatistics,
    );
}


function createOpenModalState(overrides) {
    assert.equal(typeof overrides, 'object');
    return {
        loading: false,
        saving: false,
        resetting: false,
        confirmingReset: false,
        windowDays: [1, 7, 30],
        showWindowLabels: true,
        limitNoteCreditsPerSearchContext: true,
        statistics: { retentionPopulatedDayLimit: 365, days: [] },
        ...overrides,
    };
}


test('statistics modal initializes every search suggestion setting together', () => {
    const modal = createStatisticsModal({
        readWindows: () => [2, 14],
        readShowWindowLabels: () => false,
    });

    assert.deepEqual(modal.getInitialModalState(), {
        loading: true,
        saving: false,
        resetting: false,
        confirmingReset: false,
        windowDays: [2, 14],
        showWindowLabels: false,
        limitNoteCreditsPerSearchContext: true,
        statistics: null,
    });
});


test('changing a suggestion window persists all settings immediately', async () => {
    const savedSettings = [];
    const modal = createStatisticsModal({
        saveSettings: async (...settings) => savedSettings.push(settings),
    });
    const harness = installModalStateHarness(modal, createOpenModalState({
        showWindowLabels: false,
        limitNoteCreditsPerSearchContext: false,
    }));

    // The slot's message (field-message.js) needs the page; here only the saving is checked.
    const shownProblems = [];
    modal._showWindowProblem = (index, problem) => shownProblems.push([index, problem]);
    await modal._changeWindow(1, '21');
    assert.deepEqual(shownProblems, [[1, '']], 'a good count clears its slot message');

    assert.deepEqual(savedSettings, [[[1, 21, 30], false, false]]);
    assert.deepEqual(harness.getState().windowDays, [1, 21, 30]);
    assert.equal(harness.getState().saving, false);
    assert.equal(harness.getRenderCount(), 2);
});


test('changing note-credit suppression persists immediately', async () => {
    const savedSettings = [];
    const modal = createStatisticsModal({
        saveSettings: async (...settings) => savedSettings.push(settings),
    });
    const harness = installModalStateHarness(modal, createOpenModalState({}));

    await modal._changeBooleanSetting('limitNoteCreditsPerSearchContext', false);

    assert.deepEqual(savedSettings, [[[1, 7, 30], true, false]]);
    assert.equal(harness.getState().limitNoteCreditsPerSearchContext, false);
    assert.equal(harness.getState().saving, false);
    assert.equal(harness.getRenderCount(), 2);
});


test('combined modal renders window controls, suppression, statistics, and reset', () => {
    class FakeHTMLElement {
        constructor() {
            this.innerHTML = '';
        }
    }
    globalThis.HTMLElement = FakeHTMLElement;
    const modalElement = new FakeHTMLElement();
    globalThis.document = {
        getElementById: (elementId) => {
            assert.equal(elementId, 'search-suggestion-statistics-modal');
            return modalElement;
        },
    };
    const modal = createStatisticsModal({});
    modal.getModalState = () => createOpenModalState({});
    modal._bindControls = (windowDays) => assert.deepEqual(windowDays, [1, 7, 30]);
    modal._installModalCloseButton = () => {};
    modal._focusSafeStart = () => {};

    modal.renderModalContent();

    assert.match(modalElement.innerHTML, /Search Suggestion Stats &amp; Settings/);
    assert.match(modalElement.innerHTML, /id="search-window-add-btn"/);
    assert.match(modalElement.innerHTML, /id="search-window-label-toggle"/);
    assert.match(modalElement.innerHTML, /id="search-context-credit-limit-toggle" checked/);
    assert.doesNotMatch(modalElement.innerHTML, /search-suggestion-settings-save-btn/);
    assert.match(modalElement.innerHTML, /Changes save automatically\./);
    assert.match(modalElement.innerHTML, /Collected activity/);
    assert.match(modalElement.innerHTML, /id="search-suggestion-statistics-reset-btn"/);
});


test('statistics modal resets activity and reloads its empty state', async () => {
    let loadCount = 0;
    let resetCount = 0;
    const modal = createStatisticsModal({
        loadStatistics: async () => {
            loadCount += 1;
            return { retentionPopulatedDayLimit: 365, days: [] };
        },
        resetStatistics: async () => {
            resetCount += 1;
            return true;
        },
    });
    const harness = installModalStateHarness(modal, createOpenModalState({
        confirmingReset: true,
        statistics: {
            retentionPopulatedDayLimit: 365,
            days: [{
                date: '2026-08-21',
                totalTagCredits: 1,
                tags: [{ tag: 'journal', count: 1 }],
            }],
        },
    }));

    await modal._resetActivity();

    assert.equal(resetCount, 1);
    assert.equal(loadCount, 1);
    assert.equal(harness.getState().resetting, false);
    assert.equal(harness.getState().confirmingReset, false);
    assert.deepEqual(harness.getState().statistics.days, []);
    assert.equal(harness.getRenderCount(), 2);
});


test('statistics modal keeps its displayed activity when reset is cancelled', async () => {
    let loadCount = 0;
    const statistics = {
        retentionPopulatedDayLimit: 365,
        days: [{
            date: '2026-08-21',
            totalTagCredits: 1,
            tags: [{ tag: 'journal', count: 1 }],
        }],
    };
    const modal = createStatisticsModal({
        loadStatistics: async () => {
            loadCount += 1;
            return { retentionPopulatedDayLimit: 365, days: [] };
        },
        resetStatistics: async () => false,
    });
    const harness = installModalStateHarness(modal, createOpenModalState({
        confirmingReset: true,
        statistics,
    }));

    await modal._resetActivity();

    assert.equal(loadCount, 0);
    assert.equal(harness.getState().resetting, false);
    assert.equal(harness.getState().confirmingReset, false);
    assert.equal(harness.getState().statistics, statistics);
    assert.equal(harness.getRenderCount(), 2);
});


test('statistics modal enters an in-app reset confirmation before deleting activity', () => {
    let resetCount = 0;
    const modal = createStatisticsModal({
        resetStatistics: async () => {
            resetCount += 1;
            return true;
        },
    });
    const harness = installModalStateHarness(modal, createOpenModalState({}));

    modal._requestResetConfirmation();

    assert.equal(resetCount, 0);
    assert.equal(harness.getState().confirmingReset, true);
    assert.equal(harness.getRenderCount(), 1);
});
