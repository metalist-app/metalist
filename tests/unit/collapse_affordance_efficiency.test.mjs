import assert from 'node:assert/strict';
import test from 'node:test';

const MODULE = '../../app/static/js/modules/mode-manager/services/collapse-affordance-service.js';

function createStorage() {
    const entries = new Map();
    return {
        getItem(key) { return entries.has(key) ? entries.get(key) : null; },
        setItem(key, value) { entries.set(key, String(value)); },
        removeItem(key) { entries.delete(key); },
        clear() { entries.clear(); },
    };
}

function installMeasurementCounter(t, rects) {
    const originalDocument = globalThis.document;
    const originalWindow = globalThis.window;
    const originalSessionStorage = globalThis.sessionStorage;
    const originalLocalStorage = globalThis.localStorage;
    globalThis.sessionStorage = createStorage();
    globalThis.localStorage = createStorage();
    const counter = { ranges: 0 };
    globalThis.window = { getComputedStyle() { return { lineHeight: '20px', fontSize: '16px' }; } };
    globalThis.document = {
        createRange() {
            counter.ranges += 1;
            return { selectNodeContents() {}, getClientRects() { return rects; }, detach() {} };
        },
        // The measured element stands in for its one text node.
        createTreeWalker(root) {
            let given = false;
            return { nextNode() { const node = given ? null : root; given = true; return node; } };
        },
    };
    const originalNodeFilter = globalThis.NodeFilter;
    globalThis.NodeFilter = { SHOW_TEXT: 4 };
    t.after(() => {
        globalThis.document = originalDocument;
        globalThis.NodeFilter = originalNodeFilter;
        globalThis.window = originalWindow;
        globalThis.sessionStorage = originalSessionStorage;
        globalThis.localStorage = originalLocalStorage;
    });
    return counter;
}

function createNote(dataset, classes = []) {
    const classSet = new Set(['note', ...classes]);
    const classWrites = [];
    const datasetWrites = [];
    const datasetValues = { ...dataset };
    const content = { querySelector() { return null; } };
    const toggle = { setAttribute() {}, removeAttribute() {} };
    return {
        classWrites,
        datasetWrites,
        classList: {
            add(name) { classWrites.push(['add', name]); classSet.add(name); },
            remove(name) { classWrites.push(['remove', name]); classSet.delete(name); },
            contains(name) { return classSet.has(name); },
        },
        dataset: new Proxy(datasetValues, {
            set(target, key, value) { datasetWrites.push([key, value]); target[key] = value; return true; },
        }),
        querySelector(selector) {
            if (selector === ':scope > .note-content') return content;
            if (selector === ':scope > .note-collapse-toggle') return toggle;
            return null;
        },
    };
}

const twoLines = [{ top: 0, height: 20, width: 100 }, { top: 24, height: 20, width: 100 }];

test('server-collapsible, editing, and redacted notes skip rendered measurement', async (t) => {
    const counter = installMeasurementCounter(t, twoLines);
    const { updateCollapseAffordanceForNote } = await import(MODULE);

    const serverCollapsible = createNote({ isCollapsible: 'true', isCollapsed: 'false' });
    const editing = createNote({ isCollapsible: 'false', hasChildren: 'true' }, ['editing']);
    const redacted = createNote({ isCollapsible: 'false', searchRedacted: 'true' });
    for (const note of [serverCollapsible, editing, redacted]) updateCollapseAffordanceForNote(note);

    assert.equal(counter.ranges, 0);
    assert.equal(serverCollapsible.dataset.canCollapse, 'true');
    assert.equal(editing.dataset.canCollapse, 'true');
    assert.equal(redacted.dataset.canCollapse, 'false');
});

test('undecided notes are still measured and promoted by rendered lines', async (t) => {
    const counter = installMeasurementCounter(t, twoLines);
    const { updateCollapseAffordanceForNote } = await import(MODULE);
    const note = createNote({ isCollapsible: 'false', isCollapsed: 'true' }, ['collapsed']);

    updateCollapseAffordanceForNote(note);

    assert.equal(counter.ranges, 1);
    assert.equal(note.dataset.canCollapse, 'true');
    assert.equal(note.classList.contains('collapsed'), true);
});

test('unchanged collapse state writes nothing that styles depend on', async (t) => {
    installMeasurementCounter(t, twoLines);
    const { updateCollapseAffordanceForNote } = await import(MODULE);
    const note = createNote({ isCollapsible: 'true', isCollapsed: 'true', canCollapse: 'true' }, ['collapsed']);

    updateCollapseAffordanceForNote(note);

    assert.deepEqual(note.datasetWrites, []);
    assert.deepEqual(note.classWrites, []);
});
