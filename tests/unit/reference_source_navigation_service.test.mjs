import assert from 'node:assert/strict';
import test from 'node:test';

function createStorage() {
    const entries = new Map();
    return {
        getItem(key) {
            return entries.has(key) ? entries.get(key) : null;
        },
        setItem(key, value) {
            entries.set(key, String(value));
        },
    };
}

function createTab(searchQuery = '') {
    return {
        searchQuery,
        scrollY: 0,
        scrollAnchor: null,
        sortMode: 'normal',
    };
}

test('nested reference source entries expose and dismiss one temporary context at a time', async (t) => {
    const originalDocument = globalThis.document;
    const originalHTMLElement = globalThis.HTMLElement;
    const originalSessionStorage = globalThis.sessionStorage;

    class FakeHTMLElement {
        constructor() {
            this.hidden = true;
            this.textContent = '';
            const classes = new Set();
            this.classList = {
                contains: (name) => classes.has(name),
                remove: (name) => classes.delete(name),
                toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
            };
        }

        removeAttribute(name) {
            delete this[name];
        }

        setAttribute(name, value) {
            this[name] = String(value);
        }

        querySelectorAll() {
            return [];
        }
    }

    const indicator = new FakeHTMLElement();
    const label = new FakeHTMLElement();
    const backButton = new FakeHTMLElement();
    const forwardButton = new FakeHTMLElement();
    const searchButton = new FakeHTMLElement();
    const elements = {
        'reference-source-indicator': indicator,
        'reference-source-indicator-label': label,
        'reference-view-chip-back': backButton,
        'reference-view-chip-forward': forwardButton,
        'reference-source-indicator-clear': searchButton,
        'notes-container': new FakeHTMLElement(),
    };
    globalThis.HTMLElement = FakeHTMLElement;
    globalThis.sessionStorage = createStorage();
    globalThis.document = {
        body: {
            classList: {
                add() {},
                remove() {},
            },
        },
        getElementById(id) {
            return elements[id] === undefined ? null : elements[id];
        },
    };

    t.after(() => {
        globalThis.document = originalDocument;
        globalThis.HTMLElement = originalHTMLElement;
        globalThis.sessionStorage = originalSessionStorage;
    });

    const { ModeContextInstance: ModeContext } = await import(
        '../../app/static/js/modules/mode-manager/mode-context.js'
    );
    const {
        getActiveReferenceOriginScope,
        isViewingReferenceSource,
        getActiveReferenceChain,
        getReferenceNavigationLabelForTab,
        getActiveReferenceSourceQuery,
        popReferenceNavigationEntryForActiveTab,
        pushReferenceNavigationEntry,
        pushForwardReferencePages,
        clearForwardReferencePages,
        hasForwardReferencePage,
        getReferencePageTabForContext,
        getReferencePageTabsForContext,
        getReferencePageLabelForContext,
        getActiveSearchContextTabId,
        replaceActiveReferenceNavigationQuery,
        updateReferenceSourceIndicator,
    } = await import(
        '../../app/static/js/modules/mode-manager/services/reference-source-navigation-service.js'
    );

    const originScope = {
        scopeTabId: 'original',
        searchQuery: 'project',
        sortMode: 'normal',
        isUntaggedView: false,
    };

    ModeContext.hydrateTabState({
        activeTabId: 'source-1',
        tabs: {
            original: createTab('project'),
            'source-1': createTab('uuid-1'),
            'source-2': createTab('uuid-2'),
        },
        tabOrder: ['original', 'source-1', 'source-2'],
    }, { emitUpdate: false });
    pushReferenceNavigationEntry('original', 'source-1', 'uuid-1', originScope, 'backlinks');
    assert.equal(isViewingReferenceSource(), true);
    assert.equal(getReferenceNavigationLabelForTab('original'), '');
    assert.equal(getReferenceNavigationLabelForTab('source-1'), 'Backlinks');
    assert.equal(getActiveReferenceSourceQuery(), 'uuid-1');
    assert.equal(label.textContent, 'Backlinks');
    assert.deepEqual(getActiveReferenceOriginScope(), originScope);
    assert.equal(indicator.classList.contains('is-shown'), true);
    assert.equal(backButton.classList.contains('is-unavailable'), false, 'the first level goes back to the search with ◀');
    // Only the arrows that can act show, as undo and redo do; the others keep their place.
    assert.equal(searchButton.classList.contains('is-unavailable'), true, 'one page: ◀ already goes to the search, no ⏮');
    assert.equal(forwardButton.classList.contains('is-unavailable'), true, 'not gone back yet: no ▶');

    ModeContext.hydrateTabState({
        activeTabId: 'source-2',
        tabs: {
            original: createTab('project'),
            'source-1': createTab('uuid-1'),
            'source-2': createTab('uuid-2'),
        },
        tabOrder: ['original', 'source-1', 'source-2'],
    }, { emitUpdate: false });
    pushReferenceNavigationEntry('source-1', 'source-2', 'uuid-2', originScope, 'source');
    assert.equal(getReferenceNavigationLabelForTab('source-2'), 'Source note');
    assert.deepEqual(getActiveReferenceOriginScope(), originScope);
    assert.deepEqual(getActiveReferenceChain().map((entry) => entry.toTabId), ['source-1', 'source-2']);
    assert.equal(backButton.classList.contains('is-unavailable'), false, 'a second level goes back with ◀');
    assert.equal(searchButton.classList.contains('is-unavailable'), false, 'two pages: ⏮ goes all the way back');
    pushForwardReferencePages('original', [{ referenceQuery: 'uuid-4', viewKind: 'source', scrollY: 0 }]);
    assert.equal(forwardButton.classList.contains('is-unavailable'), false, 'after going back: ▶');
    // Each search context keeps its own way forward (2026-11-14): another's shows no ▶ here.
    clearForwardReferencePages('original');
    pushForwardReferencePages('journal', [{ referenceQuery: 'uuid-5', viewKind: 'source', scrollY: 0 }]);
    assert.equal(forwardButton.classList.contains('is-unavailable'), true, 'following a new link drops what was forward');
    assert.equal(hasForwardReferencePage('journal'), true, 'journal keeps its own way forward');
    clearForwardReferencePages('journal');
    // The search context is on its deepest page; its row names the page's kind.
    assert.equal(getReferencePageTabForContext('original'), 'source-2');
    assert.equal(getReferencePageLabelForContext('original'), 'Source note');
    assert.equal(getReferencePageTabForContext('journal'), '', 'a context on its search');
    // Closing the context closes these, the deepest first: none is left for another to adopt.
    assert.deepEqual(getReferencePageTabsForContext('original'), ['source-2', 'source-1']);
    assert.deepEqual(getReferencePageTabsForContext('journal'), []);
    assert.equal(getActiveSearchContextTabId(), 'original');
    replaceActiveReferenceNavigationQuery('uuid-3', 'source');
    assert.equal(getActiveReferenceSourceQuery(), 'uuid-3');
    // A source view's chip says Source note; its first line is the tooltip.
    assert.equal(label.textContent, 'Source note');
    assert.deepEqual(popReferenceNavigationEntryForActiveTab(), {
        fromTabId: 'source-1',
        toTabId: 'source-2',
        referenceQuery: 'uuid-3',
        viewKind: 'source',
        originScope,
    });
    assert.equal(indicator.classList.contains('is-shown'), false);

    ModeContext.hydrateTabState({
        activeTabId: 'source-1',
        tabs: {
            original: createTab('project'),
            'source-1': createTab('uuid-1'),
        },
        tabOrder: ['original', 'source-1'],
    }, { emitUpdate: false });
    updateReferenceSourceIndicator();
    assert.equal(indicator.classList.contains('is-shown'), true);
    assert.equal(label.textContent, 'Backlinks');
    assert.deepEqual(popReferenceNavigationEntryForActiveTab(), {
        fromTabId: 'original',
        toTabId: 'source-1',
        referenceQuery: 'uuid-1',
        viewKind: 'backlinks',
        originScope,
    });
    assert.equal(indicator.classList.contains('is-shown'), false);

    ModeContext.syncRootIds(['root-1', 'root-2']);
    ModeContext.hydrateTabState({
        activeTabId: 'source-1',
        tabs: {
            original: createTab('project'),
            'source-1': createTab('uuid-1'),
        },
        tabOrder: ['original', 'source-1'],
    }, { emitUpdate: false, preserveActiveRootTracking: true });
    assert.equal(ModeContext.knownRootCount, 2);

    await import('../../app/static/js/modules/mode-manager/services/infinite-scroll-service.js');
    await Promise.resolve();

    // Tabs saved before a context kept its page (before 2026-11-14) can hold two ways of pages
    // from one context: its row followed the search while a page stayed open, and a link from
    // there began a second way. Loading them must not fail: the newest way is the context's page.
    ModeContext.hydrateTabState({
        activeTabId: 'way-a-1',
        tabs: {
            original: createTab('project'),
            'way-a-1': createTab('uuid-a'),
            'way-b-1': createTab('uuid-b'),
            'way-b-2': createTab('uuid-c'),
        },
        tabOrder: ['original', 'way-a-1', 'way-b-1', 'way-b-2'],
    }, { emitUpdate: false });
    pushReferenceNavigationEntry('original', 'way-a-1', 'uuid-a', originScope, 'backlinks');
    pushReferenceNavigationEntry('original', 'way-b-1', 'uuid-b', originScope, 'source');
    pushReferenceNavigationEntry('way-b-1', 'way-b-2', 'uuid-c', originScope, 'references');
    assert.equal(getReferencePageTabForContext('original'), 'way-b-2', 'the newest way');
    assert.equal(getReferencePageLabelForContext('original'), 'All references');
    assert.deepEqual(getReferencePageTabsForContext('original'), ['way-b-2', 'way-b-1', 'way-a-1']);
});
