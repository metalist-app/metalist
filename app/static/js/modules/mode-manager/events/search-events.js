import { ModeContextInstance as ModeContext } from '../mode-context.js';
import * as Logger from '../mode-logger.js';
import { CONFIG } from '../../config.js';
import { actionRefreshAndMaybeSelect } from '../actions/ui-actions.js';
import { updateSearchContextsList } from './keyboard-events.js';
import { initializeTabStateService, setTabUntaggedViewOnServer } from '../services/tab-state-service.js';
import { analyzeSearchQueryInput } from '../services/search-syntax-service.js';
import { enforceSearchInputElement, setSearchValidationState, syncSearchInputValue } from '../services/search-input-service.js';
import { CommandGate } from '../services/command-gate-service.js';
import { isDebouncedSearchPending, scheduleDebouncedSearchExecution } from '../services/search-debounce-service.js';
import { primeActiveSearchInteractionState } from '../services/search-interaction-service.js';
import { initializeSearchSuggestions, updateSearchSuggestions } from '../services/search-suggestions-service.js';
import { clearActiveNotesDom, clearCachedNotesDomForTab } from '../services/tab-dom-cache-service.js';
import {
    dismissReferenceSourceModeForActiveTab,
    isShowingNewSearchInReferenceView,
    isViewingReferenceSource,
    restoreReferenceChipAfterEmptySearch,
} from '../services/reference-source-navigation-service.js';
import { handleDictationPasteEvent, isDictationRawInsertInProgress } from '../services/dictation-paste-service.js';
import { MS_PER_SECOND } from '../../time-units.js';

// A search waits for a busy CommandGate, rechecking this often, and fails loudly
// if the gate stays busy past the limit.
const SEARCH_COMMAND_GATE_RECHECK_MS = 50;
const SEARCH_COMMAND_GATE_MAX_WAIT_SECONDS = 5;

export function resetActiveTabForSearchExecution(searchQuery, options) {
    if (typeof searchQuery !== 'string') {
        throw new Error('resetActiveTabForSearchExecution requires searchQuery string');
    }
    if (options === null || typeof options !== 'object') {
        throw new Error('resetActiveTabForSearchExecution requires options object');
    }
    const isFreshSearchInput = options.isFreshSearchInput === true;
    ModeContext.clearActiveTabDiffCacheForSearchExecution(searchQuery, {
        forceClear: isFreshSearchInput,
    });
    if (isFreshSearchInput) {
        clearActiveNotesDom();
        clearCachedNotesDomForTab(ModeContext.activeTabId);
    }
}

export function handleSearchInput(event) {
    // A dictated paste is inserted as is, then replaced by its cleaned text;
    // only the cleaned text is enforced and searched.
    if (isDictationRawInsertInProgress()) {
        return;
    }
    if (ModeContext.isLoading) {
        let currentValue = '';
        if (event && event.target && typeof event.target.value === 'string') {
            currentValue = event.target.value;
        }

        Logger.logDebug('Search input changed while request in-flight; scheduling follow-up execution', {
            value: currentValue,
            activeTab: ModeContext.activeTabId,
        }, Logger.LogCategory.EVENT);
    }

    const searchInput = event.target;
    if (!searchInput || typeof searchInput.value !== 'string') {
        throw new Error('Search input handler requires event.target input element');
    }

    if (isViewingReferenceSource()) {
        dismissReferenceSourceModeForActiveTab();
    }

    const enforcedValue = enforceSearchInputElement(searchInput);
    const analysis = analyzeSearchQueryInput(enforcedValue);
    setSearchValidationState(searchInput, analysis);
    updateSearchSuggestions(searchInput, { source: 'input' });

    Logger.logDebug('Search input changed', {
        searchQuery: analysis.normalizedText,
        length: analysis.normalizedText.length,
        isComplete: analysis.isComplete,
    }, Logger.LogCategory.EVENT);

    const previousSearchQuery = ModeContext.searchQuery;
    const wasUntaggedView = ModeContext.isUntaggedView;
    let isFreshSearchInput = previousSearchQuery !== analysis.normalizedText;
    if (wasUntaggedView) {
        isFreshSearchInput = true;
    }

    // Browser input events can re-fire with the same normalized value during autofill/composition.
    // A new search ends the Untagged view (its chip leaves) when it runs; the tab's sort order and
    // date range stay until each is ended with its × (the maintainer, 2026-11-02,
    // docs/ui/state-handling.md).
    if (isFreshSearchInput && previousSearchQuery !== analysis.normalizedText) {
        ModeContext.setSearchQuery(analysis.normalizedText);
    }

    // Update search contexts list display
    updateSearchContextsList();

    const searchRequestedAt = performance.now();

    const executeSearchWhenIdle = () => {
        const waitedMs = performance.now() - searchRequestedAt;
        if (CommandGate.isBusy()) {
            if (waitedMs > SEARCH_COMMAND_GATE_MAX_WAIT_SECONDS * MS_PER_SECOND) {
                throw new Error(`Search execution delayed >${SEARCH_COMMAND_GATE_MAX_WAIT_SECONDS}s waiting for CommandGate`);
            }
            scheduleDebouncedSearchExecution(SEARCH_COMMAND_GATE_RECHECK_MS, executeSearchWhenIdle);
            return;
        }

        const currentAnalysis = analyzeSearchQueryInput(ModeContext.searchQuery);

        if (!currentAnalysis.isComplete) {
            Logger.logNoop('Search execution skipped: incomplete query', {
                searchQuery: ModeContext.searchQuery,
                warningMessage: currentAnalysis.warningMessage,
            });
            return;
        }
        // An open last quote runs closed: "neur searches for "neur".
        const currentSearch = currentAnalysis.closedText;

        void CommandGate.run('search.execute', async () => {
            Logger.logAction('executeSearch', { searchQuery: currentSearch });
            if (wasUntaggedView && ModeContext.isUntaggedView) {
                await setTabUntaggedViewOnServer(ModeContext.activeTabId, false);
            }
            resetActiveTabForSearchExecution(currentSearch, { isFreshSearchInput });
            ModeContext.resetRootTracking({ clear: true });
            window.scrollTo(0, 0);
            // A fresh search can start while the tab is already at the top.
            if (ModeContext.getTabScrollPosition(ModeContext.activeTabId) !== 0) {
                ModeContext.updateActiveTabScroll(0);
            }
            // updateActiveTabScroll clears the scroll anchor; repeated top searches leave it null.
            if (ModeContext.getTabScrollAnchor(ModeContext.activeTabId) !== null) {
                ModeContext.updateActiveTabScrollAnchor(null);
            }
            // resetRootTracking clears the root anchor before the new search renders.
            if (ModeContext.getRootAnchorId() !== null) {
                ModeContext.setRootAnchorId(null);
            }
            // Refresh the view with the search query (let errors crash)
            await actionRefreshAndMaybeSelect({ context: 'search' });
            primeActiveSearchInteractionState();
        });
    };

    scheduleDebouncedSearchExecution(CONFIG.SEARCH.DEBOUNCE_MS, executeSearchWhenIdle);
}

/**
 * The user moves on with a quote still open (Enter, a click elsewhere, another tab):
 * the closing quote is added, to the field and to the tab's search; a quote with
 * nothing typed in it is removed (docs/ui/search-syntax.md, Completeness).
 */
export function closeOpenSearchQuote() {
    const searchInput = document.getElementById('search-input');
    if (!(searchInput instanceof HTMLInputElement)) {
        throw new Error('search-input missing from DOM');
    }
    const analysis = analyzeSearchQueryInput(searchInput.value);
    if (!analysis.endsInOpenQuote) {
        return;
    }
    searchInput.value = analysis.closedText;
    // Usually the open quote's search has run already, closed: the field and the tab's
    // search change, the list does not. Otherwise this is new typing, searched as such.
    const isAlreadyRun = ModeContext.getExecutedSearchQuery() === analysis.closedText;
    if (!isAlreadyRun || isDebouncedSearchPending()) {
        searchInput.dispatchEvent(new Event('input'));
        return;
    }
    Logger.logAction('search.close_open_quote', { searchQuery: analysis.closedText });
    setSearchValidationState(searchInput, analyzeSearchQueryInput(analysis.closedText));
    // The field can be ahead of the tab's search only while an input event is pending.
    if (ModeContext.searchQuery !== analysis.closedText) {
        ModeContext.setSearchQuery(analysis.closedText);
    }
    updateSearchContextsList();
}

// The magnifier brought the empty input out over a reference view; leaving it
// without typing brings the chip back.
function handleSearchInputBlur(event) {
    // Leaving the page (another app or window) is not moving on: typing resumes there.
    if (document.hasFocus()) {
        closeOpenSearchQuote();
    }
    if (!isShowingNewSearchInReferenceView()) {
        return;
    }
    if (event.target.value !== '') {
        return;
    }
    restoreReferenceChipAfterEmptySearch();
}

export async function initializeSearchEvents() {
    const startedAt = performance.now();
    const searchInput = document.getElementById('search-input');

    if (!searchInput || typeof searchInput.addEventListener !== 'function') {
        throw new Error('Search input element not found');
    }

    // Add input event listener
    searchInput.addEventListener('input', handleSearchInput);
    searchInput.addEventListener('paste', (event) => handleDictationPasteEvent(event, 'search'));
    searchInput.addEventListener('blur', handleSearchInputBlur);
    initializeSearchSuggestions();

    await initializeTabStateService();

    const activeTabQuery = ModeContext.searchQuery;
    if (typeof activeTabQuery !== 'string') {
        throw new Error('ModeContext.searchQuery must be a string');
    }

    // Update tab indicator on page load
    const tabIndicator = document.getElementById('tab-indicator');
    if (tabIndicator) {
        tabIndicator.textContent = ModeContext.activeTabId;
    }

    // Initialize search contexts list
    updateSearchContextsList();

    // Always sync the input field to the active tab query, except a reference view's
    // hidden note-ID search, which runs the view but never shows in the input.
    let analysis = null;
    if (isViewingReferenceSource()) {
        syncSearchInputValue(searchInput, '');
        analysis = analyzeSearchQueryInput(activeTabQuery);
    } else {
        analysis = syncSearchInputValue(searchInput, activeTabQuery);
    }
    // Tab-state hydration already seeds ModeContext.searchQuery for the active tab.
    if (ModeContext.searchQuery !== analysis.normalizedText) {
        ModeContext.setSearchQuery(analysis.normalizedText);
    }

    const initialQueryLogValue = analysis.normalizedText.length > 0 ? analysis.normalizedText : 'none';
    Logger.logAction('initialPageLoad', { searchQuery: initialQueryLogValue });

    const initialExecutableQuery = analysis.isComplete ? analysis.closedText : analysis.sanitizedText;
    // The default executed query is empty, so initial empty searches do not need a setter call.
    if (ModeContext.getExecutedSearchQuery() !== initialExecutableQuery) {
        ModeContext.setExecutedSearchQuery(initialExecutableQuery);
    }
    const initResult = await CommandGate.run('search.init_view', async () => {
        await actionRefreshAndMaybeSelect({ startedAt: startedAt, context: 'init search' });
        ModeContext.restoreScrollForActiveTab();
    });
    if (initResult === null) {
        throw new Error('Initialization should not be blocked by CommandGate');
    }

    Logger.logDebug('Search events initialized', {
        activeTab: ModeContext.activeTabId,
        restoredQuery: analysis.normalizedText,
    }, Logger.LogCategory.INIT);
}
