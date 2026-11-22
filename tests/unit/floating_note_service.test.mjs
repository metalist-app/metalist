import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {ApplicationState, stateValuesEqual} from '../../app/static/js/modules/application-state.js';
import {constrainFloatingNoteRect, moveFloatingNoteRect} from '../../app/static/js/modules/mode-manager/services/floating-note-layout.js';

const source = await readFile(new URL('../../app/static/js/modules/mode-manager/services/floating-note-service.js', import.meta.url), 'utf8');

// The server's answer for a window whose note reads `text` (/notes/{id}/floating).
function ready(revision, text) {
    return {revision, status: 'ready', structure: [{id: 'root', parentId: null, hash: text}], notes: {root: {content: text}}};
}

function harness() {
    class Element {
        constructor() { this.style = {}; this.dataset = {}; this.isConnected = false; this.scrollTop = 0; this.draws = 0; this.html = ''; }
        appendChild(child) { child.isConnected = true; }
        setAttribute() {}
        focus() {}
        remove() { this.isConnected = false; }
        querySelectorAll() { return []; }
        replaceChildren() { this.html = ''; }
    }
    const requests = [];
    const elements = [];
    const intervals = new Set();
    let sequence = 0;
    const window = {
        innerWidth: 1000, innerHeight: 800,
        addEventListener() {}, removeEventListener() {},
        setInterval() { const id = ++sequence; intervals.add(id); return id; },
        clearInterval(id) { intervals.delete(id); },
    };
    const dependencies = {
        ApplicationState, stateValuesEqual, constrainFloatingNoteRect, moveFloatingNoteRect,
        window, document: {getElementById: () => new Element()}, HTMLElement: Element,
        crypto: {randomUUID: () => String(++sequence)},
        NotesAPI: {getFloatingNote: (noteId, revision) => new Promise((resolve, reject) => requests.push({noteId, revision, resolve, reject}))},
        CommandGate: {isBusy: () => false},
        rethrowUnexpectedError: error => { throw error; },
        createFloatingNoteElements() {
            const entry = Object.fromEntries(['element', 'tree', 'title', 'status', 'scroll'].map(key => [key, new Element()]));
            elements.push(entry);
            return entry;
        },
        getFloatingNoteTitle: () => 'Root',
        applyFloatingNoteRect() {}, hydrateImageFilePreviews() {}, hydrateEmailPreviews: async () => [], hydrateExcalidrawPreviews: async () => [], ensureAnchorsOpenInNewTabs() {},
        hydrateRemoteImageProxies() {}, queueMermaidDiagramRendering: async () => {},
        serverRenderedHtml: html => html,
        watchFoldArrows() {},
        // No note is edited in a window here (editing-surface.js).
        editedWindowHost: () => null, recordPress() {}, editNoteInWindow: async () => {}, actionDeselectNote: async () => {},
        // The notes as the list draws them (floating-note-editing.js): here, the root's text.
        drawWindowNotes(container, structure, notes) { container.html = notes[structure[0].id].content; container.draws++; },
        watchFoldability() {}, captureClickAnchor() {}, collapseNote: async () => {}, expandNote: async () => {},
        galleryElementOf() {}, galleryNoteIdOf() {}, toggleGalleryOutline: async () => {},
    };
    const build = new Function(...Object.keys(dependencies), source.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '')
        + '\nreturn {openFloatingNote, closeFloatingNote, closeAllFloatingNotes, refreshFloatingNotes};');
    return {service: build(...Object.values(dependencies)), requests, elements, intervals};
}

test('closing all windows discards in-flight plaintext and releases the refresh timer', async () => {
    const h = harness();
    const pending = h.service.openFloatingNote('root');
    assert.equal(h.intervals.size, 1);
    h.service.closeAllFloatingNotes();
    h.service.closeAllFloatingNotes();
    h.requests[0].resolve(ready('a', '<p>Do not republish</p>'));
    await pending;
    assert.equal(h.elements[0].tree.draws, 0);
    assert.equal(h.elements[0].element.isConnected, false);
    assert.equal(h.intervals.size, 0);
});

test('unchanged windows retain their DOM and deletion/restore refreshes the same window', async () => {
    const h = harness();
    const opened = h.service.openFloatingNote('root');
    h.requests.shift().resolve(ready('a', '<p>Root</p>'));
    await opened;
    for (const snapshot of [
        {revision: 'a', status: 'unchanged', structure: [], notes: {}},
        ready('b', '<p>Root</p>'),
    ]) {
        const pending = h.service.refreshFloatingNotes();
        h.requests.shift().resolve(snapshot);
        await pending;
    }
    assert.equal(h.elements[0].tree.draws, 1);
    const deleted = h.service.refreshFloatingNotes();
    h.requests.shift().resolve({revision: 'c', status: 'deleted', structure: [], notes: {}});
    await deleted;
    assert.equal(h.elements[0].tree.html, '');
    assert.equal(h.elements[0].status.textContent, 'This note was deleted.');
    const restored = h.service.refreshFloatingNotes();
    h.requests.shift().resolve(ready('d', '<p>Restored</p>'));
    await restored;
    assert.equal(h.elements[0].tree.html, '<p>Restored</p>');
    h.service.closeAllFloatingNotes();
});

test('refresh calls cannot overlap and a closed window cannot overwrite a reopened one', async () => {
    const h = harness();
    const opening = h.service.openFloatingNote('root');
    h.requests.shift().resolve(ready('a', '<p>First</p>'));
    const id = await opening;
    const refreshing = h.service.refreshFloatingNotes();
    await h.service.refreshFloatingNotes();
    assert.equal(h.requests.length, 1);
    h.service.closeFloatingNote(id);
    const reopening = h.service.openFloatingNote('root');
    h.requests[1].resolve(ready('c', '<p>New window</p>'));
    await reopening;
    h.requests[0].resolve(ready('b', '<p>Old response</p>'));
    await refreshing;
    assert.equal(h.elements[1].tree.html, '<p>New window</p>');
    h.service.closeAllFloatingNotes();
});

test('malformed responses and internal failures still throw', async () => {
    const h = harness();
    const pending = h.service.openFloatingNote('root');
    h.requests.shift().resolve({revision: 'a', status: 'ready', structure: [], notes: {}});
    await assert.rejects(pending, /do not match/);
    const refreshing = h.service.refreshFloatingNotes();
    h.requests.shift().reject(new Error('Internal bug'));
    await assert.rejects(refreshing, /Internal bug/);
    h.service.closeAllFloatingNotes();
});
