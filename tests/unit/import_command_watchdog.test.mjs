import assert from 'node:assert/strict';
import test from 'node:test';

// An import lasts as long as its files take, and shows its own progress: CommandGate's
// watchdog for a stuck command must not call it stuck (0.26.0, 2026-11-05: 1,127 files
// passed the 15 seconds, and the fatal overlay said the import was stuck while it ran on).

const AN_HOUR_MS = 60 * 60 * 1000;

function withPageGlobals(t) {
    const originalSessionStorage = globalThis.sessionStorage;
    globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
    // Its imports (the login) set globals on the page.
    const hadWindow = typeof globalThis.window !== 'undefined';
    if (!hadWindow) globalThis.window = {};
    // The busy spinner's class goes on the page.
    const hadDocument = typeof globalThis.document !== 'undefined';
    if (!hadDocument) globalThis.document = { body: { classList: { add() {}, remove() {} } } };
    t.after(() => {
        if (!hadWindow) delete globalThis.window;
        if (!hadDocument) delete globalThis.document;
        if (typeof originalSessionStorage === 'undefined') {
            delete globalThis.sessionStorage;
        } else {
            globalThis.sessionStorage = originalSessionStorage;
        }
    });
}

test('an import running for an hour is never called stuck', async (t) => {
    withPageGlobals(t);
    const { runImport } = await import('../../app/static/js/modules/wizard/import-wizard-steps.js');
    const { NotesAPI } = await import('../../app/static/js/modules/api-client.js');
    let finishImport = null;
    t.mock.method(NotesAPI, 'importBookmarks', () => new Promise((resolve) => {
        finishImport = () => resolve({ noteCount: 1, sourceTag: 'bookmarks' });
    }));
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const wizard = {
        choices: { source: 'bookmarks', bookmarksText: '<DL></DL>', prefixText: '', addToExisting: false, isDrop: false },
        services: { afterImport: async () => {} },
    };
    const progress = { working() {}, counted() {} };

    const imported = runImport(wizard, progress);
    await new Promise(setImmediate);
    assert.equal(typeof finishImport, 'function', 'the import is under way');
    assert.doesNotThrow(() => t.mock.timers.tick(AN_HOUR_MS));
    finishImport();
    await imported;
});
