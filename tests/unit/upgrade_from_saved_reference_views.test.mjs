import assert from 'node:assert/strict';
import test from 'node:test';

import {
    CONTEXT, CSV_BACKLINKS, LEFT_OPEN, PAGES, SAVED_BY_0_29_0, loadSavedTabs,
} from './saved_reference_views_harness.mjs';

// Reference views as 0.29.0 saved them load as reference pages (saved_reference_views_harness.mjs
// says how they were made). The page left open by its closed search context was adopted by the
// page beside it, which then counted as its search context (2026-11-14).
test('reference views saved by 0.29.0 load as reference pages of their search context', async (t) => {
    const { ModeContext, navigation } = await loadSavedTabs(t, SAVED_BY_0_29_0);

    assert.equal(ModeContext.activeTabId, LEFT_OPEN);
    assert.equal(navigation.isViewingReferenceSource(), true, 'the page left open is a reference page');
    assert.equal(navigation.getReferenceNavigationLabelForTab(LEFT_OPEN), 'Source note', 'no tab is named by a note ID');
    // Every page belongs to the one search context left: none is a search context itself.
    assert.equal(navigation.getActiveSearchContextTabId(), CONTEXT);
    for (const page of PAGES) {
        assert.notEqual(navigation.getReferenceNavigationLabelForTab(page), '', `${page} is a page`);
        assert.equal(navigation.getReferencePageTabForContext(page), '', `${page} is not a search context`);
    }
    assert.deepEqual(
        navigation.getReferencePageTabsForContext(CONTEXT).toSorted(), PAGES.toSorted(),
        'closing the context closes every page saved from it',
    );
    // ◀ from the page left open goes to the page beside it, which adopted it.
    assert.deepEqual(navigation.getActiveReferenceChain().map((entry) => entry.toTabId), [CSV_BACKLINKS, LEFT_OPEN]);
    // What is saved back is what this version saves: each page's origin is the search context.
    const views = navigation.getReferenceViewsPayload();
    assert.deepEqual(Object.keys(views).toSorted(), PAGES.toSorted());
    for (const view of Object.values(views)) {
        assert.equal(view.originScope.scopeTabId, CONTEXT);
    }
});
