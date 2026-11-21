import assert from 'node:assert/strict';
import test from 'node:test';

// A dropped file took the time it was uploaded as its dates (found 2026-11-20): the upload now
// carries when the file was last changed, before the file itself (the server reads the form in order).
test('an uploaded dropped file carries the date it was last changed, before its content', async (t) => {
    const originalSessionStorage = globalThis.sessionStorage;
    const originalFetch = globalThis.fetch;
    const stored = new Map([['metalist_tab_id', 'tab']]);
    globalThis.sessionStorage = {
        getItem(key) { return stored.has(key) ? stored.get(key) : null; },
        setItem(key, value) { stored.set(key, value); },
        removeItem(key) { stored.delete(key); },
    };
    const hadWindow = typeof globalThis.window !== 'undefined';
    if (!hadWindow) globalThis.window = {};
    t.after(() => {
        if (!hadWindow) delete globalThis.window;
        globalThis.fetch = originalFetch;
        if (typeof originalSessionStorage === 'undefined') {
            delete globalThis.sessionStorage;
        } else {
            globalThis.sessionStorage = originalSessionStorage;
        }
    });
    const sent = [];
    globalThis.fetch = async (_url, request) => {
        sent.push([...request.body.entries()].map(([name, value]) => [name, typeof value === 'string' ? value : 'the file']));
        return { ok: true, json: async () => ({ stored: 'notes/plan.md' }) };
    };
    const { NotesAPI } = await import('../../app/static/js/modules/api-client.js');
    const { initializeSessionIdentity } = await import('../../app/static/js/modules/session-auth.js');
    initializeSessionIdentity();
    const changedAt = Date.UTC(2026, 9, 15, 9, 0);
    const file = new File(['# Plan\n'], 'plan.md', { lastModified: changedAt });

    await NotesAPI.uploadImportFile('upload', 'notes/plan.md', file);

    assert.deepEqual(sent, [[['path', 'notes/plan.md'], ['modified', String(changedAt)], ['file', 'the file']]]);
    await assert.rejects(() => NotesAPI.uploadImportFile('upload', 'notes/plan.md', new Blob(['x'])), /requires the upload/);
});
