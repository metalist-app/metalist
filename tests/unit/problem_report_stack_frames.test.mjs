import assert from 'node:assert/strict';
import test from 'node:test';

// The report maker loads the page's state, which reads the browser's session storage.
const stored = new Map();
globalThis.sessionStorage = {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => { stored.set(key, value); },
    removeItem: (key) => { stored.delete(key); },
};
const { stackFrames } = await import('../../app/static/js/modules/problem-reports/report-maker.js');

// A report's frames are the code's own lines from the error's stack. MetaList serves its scripts
// under the version of its files (`/static/v/<hash>/js/…`), which the pattern did not allow: every
// report came with no frames (found 2026-11-18, in the maintainer's report of a failed export in
// Firefox and his dad's screenshot in Chrome).

test('a Firefox stack under the versioned address gives its frames', () => {
    const stack = [
        'HttpRequestError@http://127.0.0.1:9000/static/v/c97c25cccdba8949/js/modules/expected-errors.js:21:9',
        '_fetchExportDocument@http://127.0.0.1:9000/static/v/c97c25cccdba8949/js/modules/api-client.js:1560:19',
    ].join('\n');

    assert.deepEqual(stackFrames(stack), ['modules/expected-errors.js:21 HttpRequestError', 'modules/api-client.js:1560 _fetchExportDocument']);
});

test('a Chrome stack under the versioned address gives its frames', () => {
    const stack = [
        'Error: Problem report failed: 401 Unauthorized',
        '    at answerOf (http://127.0.0.1:8001/static/v/77f419a913c3b482/js/modules/problem-reports/report-maker.js:106:15)',
        '    at async makeReport (http://127.0.0.1:8001/static/v/77f419a913c3b482/js/modules/problem-reports/report-maker.js:117:20)',
    ].join('\n');

    assert.deepEqual(stackFrames(stack), ['modules/problem-reports/report-maker.js:106 answerOf', 'modules/problem-reports/report-maker.js:117 makeReport']);
});

test('an address with no version still gives its frame, and a line from elsewhere gives none', () => {
    assert.deepEqual(stackFrames('at refresh (http://host/static/js/modules/ui-actions.js:88:3)'), ['modules/ui-actions.js:88 refresh']);
    assert.deepEqual(stackFrames('at run (https://cdn.example/lib.js:1:1)'), []);
});
