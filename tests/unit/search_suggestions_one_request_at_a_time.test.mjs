import assert from 'node:assert/strict';
import test from 'node:test';

// Typing asks for suggestions once at a time: while one request is out, typing only keeps the
// latest text, asked for when the answer comes. Each keystroke asked while the last was out, the
// server answered every one in turn, and on a slow machine a page then waited a minute for its
// notes (a problem report, 2026-11-14).

// Past the debounce (search-suggestions-service.js, SUGGESTION_DEBOUNCE_MS).
const PAST_THE_DEBOUNCE_MS = 120;

function createStorage() {
    const entries = new Map();
    return {
        getItem: (key) => (entries.has(key) ? entries.get(key) : null),
        setItem: (key, value) => entries.set(key, String(value)),
        removeItem: (key) => entries.delete(key),
    };
}

function settle() {
    return new Promise((resolve) => setTimeout(resolve, PAST_THE_DEBOUNCE_MS));
}

test('typing while suggestions are asked for sends only the latest text, once the answer comes', async (t) => {
    const originals = {
        document: globalThis.document, window: globalThis.window,
        sessionStorage: globalThis.sessionStorage, localStorage: globalThis.localStorage,
    };
    t.after(() => Object.assign(globalThis, originals));
    const input = { value: '', selectionStart: 0 };
    const container = { hidden: true, style: { display: 'none' }, innerHTML: '' };
    globalThis.document = {
        activeElement: input,
        getElementById: (id) => (id === 'search-suggestions' ? container : null),
    };
    globalThis.window = {};
    globalThis.sessionStorage = createStorage();
    globalThis.localStorage = createStorage();

    const { NotesAPI } = await import('../../app/static/js/modules/api-client.js');
    const { updateSearchSuggestions } = await import(
        '../../app/static/js/modules/mode-manager/services/search-suggestions-service.js'
    );
    const asked = [];
    const answers = [];
    NotesAPI.fetchSearchSuggestions = (query) => {
        asked.push(query);
        return new Promise((resolve) => {
            answers.push(() => resolve({ suggestions: [], personalizedSuggestions: [], reasons: {}, labels: {} }));
        });
    };
    function type(text) {
        input.value = text;
        input.selectionStart = text.length;
        updateSearchSuggestions(input, { source: 'input' });
    }

    type('w');
    await settle();
    assert.deepEqual(asked, ['w'], 'the first pause asks');

    for (const text of ['wo', 'wor', 'work']) {
        type(text);
        await settle();
    }
    assert.deepEqual(asked, ['w'], 'nothing more is asked while that answer is out');

    answers[0]();
    await settle();
    assert.deepEqual(asked, ['w', 'work'], 'the latest text is asked for when the answer comes');

    answers[1]();
    await settle();
    assert.deepEqual(asked, ['w', 'work'], 'nothing is left to ask');
});
