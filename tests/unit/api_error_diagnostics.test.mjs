import assert from 'node:assert/strict';
import test from 'node:test';

import { describeApiFailure } from '../../app/static/js/modules/api-error-diagnostics.js';

test('500 includes safe server diagnostic in the visible error', async () => {
    const response = new Response(JSON.stringify({
        detail: 'Internal server error',
        diagnostic: {
            errorType: 'ValueError', codeLocation: 'app/api/routes/notes.py:42',
            requestId: 'a1b2c3d4',
        },
    }), { status: 500, statusText: 'Internal Server Error', headers: { 'content-type': 'application/json', 'x-request-id': 'a1b2c3d4' } });

    assert.equal(
        await describeApiFailure(response),
        'API call failed: 500 Internal Server Error (ValueError at app/api/routes/notes.py:42, request a1b2c3d4)',
    );
});

test('unrecognized and non-500 bodies are not shown in the visible error', async () => {
    const body = JSON.stringify({ diagnostic: {
        errorType: 'ValueError', codeLocation: 'C:/Users/private/notes.txt:42',
    }, secret: 'PRIVATE_NOTE_CONTENT' });
    const serverError = new Response(body, { status: 500, statusText: 'Internal Server Error', headers: { 'content-type': 'application/json' } });
    const badRequest = new Response(body, { status: 400, statusText: 'Bad Request', headers: { 'content-type': 'application/json' } });
    const traversal = new Response(JSON.stringify({ diagnostic: {
        errorType: 'ValueError', codeLocation: 'app/../../private.py:42',
    } }), { status: 500, statusText: 'Internal Server Error', headers: { 'content-type': 'application/json' } });

    assert.equal(await describeApiFailure(serverError), 'API call failed: 500 Internal Server Error');
    assert.equal(await describeApiFailure(badRequest), 'API call failed: 400 Bad Request');
    assert.equal(await describeApiFailure(traversal), 'API call failed: 500 Internal Server Error');
});

test('invalid request identifiers are not copied into the visible error', async () => {
    const response = new Response(JSON.stringify({ diagnostic: {
        errorType: 'TypeError', codeLocation: 'app/services/content_formatting.py:186',
        requestId: 'a1b2c3d4',
    } }), { status: 500, statusText: 'Internal Server Error', headers: { 'content-type': 'application/json', 'x-request-id': 'PRIVATE_NOTE_CONTENT' } });
    assert.equal(
        await describeApiFailure(response),
        'API call failed: 500 Internal Server Error (TypeError at app/services/content_formatting.py:186)',
    );
});

test('every failed answer names its request id from the header, so a 409 matches its server log line', async () => {
    const conflict = new Response(JSON.stringify({ detail: 'PRIVATE_NOTE_CONTENT' }), {
        status: 409, statusText: 'Conflict', headers: { 'content-type': 'application/json', 'x-request-id': '3fa2c1d0' },
    });
    const missing = new Response('PRIVATE_NOTE_CONTENT', { status: 404, statusText: 'Not Found', headers: { 'x-request-id': '0badf00d' } });
    const unnamed = new Response('', { status: 503, statusText: 'Service Unavailable' });

    assert.equal(await describeApiFailure(conflict), 'API call failed: 409 Conflict (request 3fa2c1d0)');
    assert.equal(await describeApiFailure(missing), 'API call failed: 404 Not Found (request 0badf00d)');
    assert.equal(await describeApiFailure(unnamed), 'API call failed: 503 Service Unavailable');
});
