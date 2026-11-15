import assert from 'node:assert/strict';
import test from 'node:test';

import { showFatalError } from '../../app/static/js/modules/error-overlay.js';

// The same fatal error raised again while the overlay shows it (a failing check that repeats,
// or one failure reported twice): found 2026-11-15, the overlay stored the same error a second
// time, which MetaList's state refuses as a redundant change. That refusal was thrown from the
// error listener, became a fatal error of its own, and replaced the real one on the overlay and
// in Export Report….

class FakeElement {
    constructor() {
        this.id = '';
        this.style = {};
        this.textContent = '';
        this.children = [];
    }

    append(...children) {
        this.children.push(...children);
    }

    appendChild(child) {
        this.children.push(child);
        fakeDocument.byId.set(child.id, child);
        return child;
    }

    addEventListener() {}

    querySelector(selector) {
        const id = selector.replace(/^#/, '');
        return this.children.find((child) => child.id === id);
    }
}

const fakeDocument = {
    byId: new Map(),
    body: null,
    getElementById(id) {
        return this.byId.has(id) ? this.byId.get(id) : null;
    },
    createElement() {
        return new FakeElement();
    },
};

test('the same fatal error twice keeps showing it, and raises nothing of its own', () => {
    fakeDocument.body = new FakeElement();
    globalThis.document = fakeDocument;
    globalThis.HTMLElement = FakeElement;
    globalThis.fetch = async () => ({ status: 200, ok: true, json: async () => ({ stale: false }) });

    showFatalError('Snapshot answer is malformed', 'at refresh (ui-actions.js:88)', 'Error');
    showFatalError('Snapshot answer is malformed', 'at refresh (ui-actions.js:88)', 'Error');

    const text = fakeDocument.getElementById('fatal-error-overlay').querySelector('#fatal-error-text').textContent;
    assert.match(text, /FATAL: Snapshot answer is malformed/);
});
