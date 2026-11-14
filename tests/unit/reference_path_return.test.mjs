import assert from 'node:assert/strict';
import test from 'node:test';

// Following a reference already open on the current path goes back to its level instead of
// opening a new tab (docs/ui/references.md, Reference views; agreed 2026-10-29).

function createTab(searchQuery) {
    return { searchQuery, scrollY: 0, scrollAnchor: null, sortMode: 'normal' };
}

function installFakeDocument(t) {
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
    const elements = Object.fromEntries([
        'reference-source-indicator', 'reference-source-indicator-label', 'reference-view-chip-icon',
        'reference-view-chip-back', 'reference-view-chip-forward', 'reference-source-indicator-clear', 'notes-container',
    ].map((id) => [id, new FakeHTMLElement()]));
    const entries = new Map();
    globalThis.HTMLElement = FakeHTMLElement;
    globalThis.sessionStorage = {
        getItem: (key) => (entries.has(key) ? entries.get(key) : null),
        setItem: (key, value) => entries.set(key, String(value)),
    };
    globalThis.document = {
        body: { classList: { add() {}, remove() {} } },
        getElementById: (id) => (elements[id] === undefined ? null : elements[id]),
    };
    t.after(() => {
        globalThis.document = originalDocument;
        globalThis.HTMLElement = originalHTMLElement;
        globalThis.sessionStorage = originalSessionStorage;
    });
}

test('a reference already on the path is found at its level, and the levels above it close', async (t) => {
    installFakeDocument(t);
    const { ModeContextInstance: ModeContext } = await import(
        '../../app/static/js/modules/mode-manager/mode-context.js'
    );
    const {
        findReferenceLevelOnActivePath,
        getActiveReferenceChain,
        popReferenceLevelsAbove,
        pushReferenceNavigationEntry,
    } = await import('../../app/static/js/modules/mode-manager/services/reference-source-navigation-service.js');

    const scope = { scopeTabId: 'search', searchQuery: 'project', sortMode: 'normal', isUntaggedView: false };
    const otherScope = { ...scope, scopeTabId: 'other-search', searchQuery: 'other' };
    const tabs = {
        search: createTab('project'),
        a: createTab('note-a'),
        b: createTab('note-b'),
        c: createTab('note-c'),
        'other-search': createTab('other'),
        'other-a': createTab('note-a'),
    };
    const tabOrder = Object.keys(tabs);
    const activate = (activeTabId) => ModeContext.hydrateTabState({ activeTabId, tabs, tabOrder }, { emitUpdate: false });

    // Another search's path also shows A: it is not this path (case 6).
    activate('other-a');
    pushReferenceNavigationEntry('other-search', 'other-a', 'note-a', otherScope, 'source');
    // This path: search → A → B → C.
    activate('a');
    pushReferenceNavigationEntry('search', 'a', 'note-a', scope, 'source');
    activate('b');
    pushReferenceNavigationEntry('a', 'b', 'note-b', scope, 'source');
    activate('c');
    pushReferenceNavigationEntry('b', 'c', 'note-c', scope, 'source');

    assert.equal(findReferenceLevelOnActivePath('note-a', 'source'), 'a', 'A, two levels back (case 2)');
    assert.equal(findReferenceLevelOnActivePath('note-b', 'source'), 'b', 'B, one level back (case 1)');
    assert.equal(findReferenceLevelOnActivePath('note-c', 'source'), 'c', 'the view shown now (case 3)');
    assert.equal(findReferenceLevelOnActivePath('note-d', 'source'), '', 'a note not on the path (case 4)');
    assert.equal(findReferenceLevelOnActivePath('note-a', 'backlinks'), '', 'the same notes as another kind of view');

    assert.deepEqual(popReferenceLevelsAbove('a').map((entry) => entry.toTabId), ['c', 'b'],
        'going back to A leaves C and B, the nearest first');
    activate('a');
    assert.deepEqual(getActiveReferenceChain().map((entry) => entry.toTabId), ['a'], 'A stays, opened from the search');
    activate('other-a');
    assert.deepEqual(getActiveReferenceChain().map((entry) => entry.toTabId), ['other-a'], 'the other path is untouched');
    assert.throws(() => popReferenceLevelsAbove('b'), /not on the active reference path/);
});
