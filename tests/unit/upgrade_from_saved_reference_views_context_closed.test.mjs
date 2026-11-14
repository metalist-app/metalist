import assert from 'node:assert/strict';
import test from 'node:test';

import { CONTEXT, CSV_SOURCE, PAGES, SAVED_BY_0_29_0, TRIP_BACKLINKS, loadSavedTabs } from './saved_reference_views_harness.mjs';

// 0.29.0 closed a search context and left its reference views open, as search contexts of their
// own. A view two steps in still names the closed context as its origin. Here the first context
// of SAVED_BY_0_29_0 (saved_reference_views_harness.mjs) was closed so, beside another context.
const OTHER_CONTEXT = 'c0ffee00-0000-4000-8000-000000000001';

function savedWithTheFirstContextClosed() {
    const state = structuredClone(SAVED_BY_0_29_0);
    delete state.tabs[CONTEXT];
    state.tabs[OTHER_CONTEXT] = { ...SAVED_BY_0_29_0.tabs[CONTEXT], searchQuery: 'sample' };
    state.tabOrder = [OTHER_CONTEXT, ...state.tabOrder.filter((tabId) => tabId !== CONTEXT)];
    // 0.29.0 kept, of the views from the closed context, only the one opened from a view.
    state.referenceViews = { [CSV_SOURCE]: state.referenceViews[CSV_SOURCE] };
    state.activeTabId = CSV_SOURCE;
    return state;
}

test('pages left by a search context 0.29.0 closed belong to a search context that is there', async (t) => {
    const { navigation } = await loadSavedTabs(t, savedWithTheFirstContextClosed());

    assert.equal(navigation.isViewingReferenceSource(), true);
    assert.equal(navigation.getActiveSearchContextTabId(), OTHER_CONTEXT, 'not the closed one');
    assert.deepEqual(navigation.getReferencePageTabsForContext(OTHER_CONTEXT).toSorted(), PAGES.toSorted());
    assert.deepEqual(navigation.getReferencePageTabsForContext(CONTEXT), []);
    // In tab order: the context, then each page opened from the one before it.
    assert.deepEqual(navigation.getActiveReferenceChain().map((entry) => entry.toTabId), [TRIP_BACKLINKS, CSV_SOURCE]);
    for (const view of Object.values(navigation.getReferenceViewsPayload())) {
        assert.equal(view.originScope.scopeTabId, OTHER_CONTEXT);
    }
});
