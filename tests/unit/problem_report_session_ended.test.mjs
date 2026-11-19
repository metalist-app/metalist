import assert from 'node:assert/strict';
import test from 'node:test';

// A report asked for by a page whose session has ended (the maintainer's dad, 2026-11-18: after
// a restore, Export Report… on the red error was answered 401, and that failure took the place
// of the error he wanted to report). The page then makes the report as the login page does,
// with nothing from the vault, so a file is still saved.

const TAB_ID = '10000000-0000-4000-8000-0000000000e1';
const UNAUTHORIZED = 401;
const OK = 200;
const SERVER_ERROR = 500;

function answer(status, body) {
    return { status, ok: status === OK, statusText: status === UNAUTHORIZED ? 'Unauthorized' : 'Other', json: async () => body };
}

function draftOfASignedInPage() {
    return {
        madeBy: 'overlay', description: '',
        error: { className: 'TypeError', message: 'restore went wrong', frames: ['modules/x.js:12 restore'] },
        window: { w: 1200, h: 800 }, view: { notesInList: 3, notesOnScreen: 3, scrollY: 0 },
        theme: 'light', skin: '', preferences: [],
        editingNote: '20000000-0000-4000-8000-0000000000e2',
        search: 'groceries',
        noteIds: ['20000000-0000-4000-8000-0000000000e2'],
        inputs: [{ t: 0, kind: 'click', note: '20000000-0000-4000-8000-0000000000e2', part: 'content', control: '', command: '', code: '', mods: [], typed: '' }],
        commands: [{ t: 0, label: 'backup.restore', ms: 40, outcome: 'error' }],
        requests: [{ t: 0, method: 'POST', path: '/api2/backups/restore', status: 200, ms: 900, requestId: 'r1' }],
    };
}

async function loadSignedInPage(t, answers) {
    const originals = { document: globalThis.document, sessionStorage: globalThis.sessionStorage, fetch: globalThis.fetch };
    t.after(() => Object.assign(globalThis, originals));
    const stored = new Map([['metalist_tab_id', TAB_ID]]);
    globalThis.sessionStorage = {
        getItem: (key) => (stored.has(key) ? stored.get(key) : null),
        setItem: (key, value) => { stored.set(key, value); },
        removeItem: (key) => { stored.delete(key); },
    };
    globalThis.document = { body: { dataset: { appReady: 'true' } } };
    const asked = [];
    globalThis.fetch = async (url, options) => {
        asked.push({ url, headers: options.headers, body: JSON.parse(options.body) });
        return answers[asked.length - 1];
    };
    const { initializeSessionIdentity } = await import('../../app/static/js/modules/session-auth.js');
    initializeSessionIdentity();
    const { makeReport } = await import('../../app/static/js/modules/problem-reports/report-maker.js');
    return { makeReport, asked };
}

test('a report asked for after the session ended is made as the login page makes one', async (t) => {
    const { makeReport, asked } = await loadSignedInPage(t, [
        answer(UNAUTHORIZED, { detail: 'Not authenticated' }),
        answer(OK, { report: { madeBy: 'overlay' } }),
    ]);

    const report = await makeReport(draftOfASignedInPage());

    assert.deepEqual(report, { madeBy: 'overlay' });
    assert.deepEqual(asked.map((request) => request.url), ['/api2/problem-reports', '/api2/problem-reports/unsaved']);
    const again = asked[1];
    assert.deepEqual(again.headers, { 'Content-Type': 'application/json' });
    // Nothing from the vault: the server cannot read its notes or tags to check the report.
    assert.deepEqual([again.body.noteIds, again.body.search, again.body.editingNote, again.body.inputs], [[], '', '', []]);
    // The error and what the page did stay.
    assert.deepEqual(again.body.error, draftOfASignedInPage().error);
    assert.deepEqual(again.body.commands, draftOfASignedInPage().commands);
    assert.deepEqual(again.body.requests, draftOfASignedInPage().requests);
});

test('a report the server will not make at all fails as a refused request, to be shown calmly', async (t) => {
    const { makeReport } = await loadSignedInPage(t, [
        answer(UNAUTHORIZED, { detail: 'Not authenticated' }),
        answer(SERVER_ERROR, { detail: 'broken' }),
    ]);
    const { HttpRequestError } = await import('../../app/static/js/modules/expected-errors.js');

    await assert.rejects(makeReport(draftOfASignedInPage()), (error) => {
        assert.ok(error instanceof HttpRequestError, `an expected request failure, not ${error.name}`);
        assert.match(error.message, /Problem report failed: 500/);
        return true;
    });
});
