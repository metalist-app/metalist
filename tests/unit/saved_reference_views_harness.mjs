// Loads tabs as an older MetaList saved them into the reference navigation, as a page load does
// (upgrade_from_saved_reference_views*.test.mjs). The navigation restores once per page load, so
// each test file loads one saved state.
import { readFileSync } from 'node:fs';

// Tabs as MetaList 0.29.0 saved them, made in a throwaway 0.29.0 on 2026-11-14 the way its
// reference views were used: from the first search context, Referenced by on Trip plan and then
// the CSV's Source note from it, and Referenced by on the CSV; then a second context, searched,
// its own Source note followed, and the context closed with its page left open (shown, as the
// active tab). Customers upgrade from such state (the maintainer, 2026-11-14).
export const SAVED_BY_0_29_0 = JSON.parse(
    readFileSync(new URL('../fixtures/upgrade/tab-state-v0.29.0.json', import.meta.url), 'utf8'),
);

export const CONTEXT = 'ef7b4ecf-00a2-4938-91a8-0b25ae8d5f47';
export const TRIP_BACKLINKS = 'baf9f2e7-3494-4036-901e-2b7d85c6eb2e';
export const CSV_SOURCE = 'bc7dcdd5-7d2f-4fa1-863f-0205b3e949e6';
export const CSV_BACKLINKS = 'b7107d8e-9f0b-4945-8d4a-608c21371acf';
// The page whose search context was closed: saved as a tab of note IDs that no view claims.
export const LEFT_OPEN = 'a35fe734-4758-4f87-80d1-99414032c6bc';
export const PAGES = [TRIP_BACKLINKS, CSV_SOURCE, CSV_BACKLINKS, LEFT_OPEN];

function createStorage() {
    const entries = new Map();
    return {
        getItem: (key) => (entries.has(key) ? entries.get(key) : null),
        setItem: (key, value) => entries.set(key, String(value)),
        removeItem: (key) => entries.delete(key),
    };
}

class FakeHTMLElement {
    constructor() {
        this.hidden = true;
        this.textContent = '';
        const classes = new Set();
        this.classList = {
            contains: (name) => classes.has(name),
            add: (name) => classes.add(name),
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

/** The modules after `state` loaded, with a stand-in page for what they draw. */
export async function loadSavedTabs(t, state) {
    const originals = {
        document: globalThis.document, HTMLElement: globalThis.HTMLElement, sessionStorage: globalThis.sessionStorage,
    };
    t.after(() => Object.assign(globalThis, originals));
    const elements = new Map();
    globalThis.HTMLElement = FakeHTMLElement;
    globalThis.sessionStorage = createStorage();
    globalThis.document = {
        body: { classList: { add() {}, remove() {} } },
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, new FakeHTMLElement());
            return elements.get(id);
        },
        querySelector: () => null,
    };
    const { ModeContextInstance: ModeContext } = await import('../../app/static/js/modules/mode-manager/mode-context.js');
    const navigation = await import('../../app/static/js/modules/mode-manager/services/reference-source-navigation-service.js');
    ModeContext.hydrateTabState(
        { activeTabId: state.activeTabId, tabs: state.tabs, tabOrder: state.tabOrder }, { emitUpdate: false },
    );
    navigation.restoreReferenceNavigation(state);
    return { ModeContext, navigation };
}
