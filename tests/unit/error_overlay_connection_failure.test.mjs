import assert from 'node:assert/strict';
import test from 'node:test';

import {
    isBrowserResizeObserverNote,
    rejectedInputWarning,
    shouldSuppressFatalOverlay,
} from '../../app/static/js/modules/error-overlay.js';
import { HttpRequestError, ServerInputRejectedError } from '../../app/static/js/modules/expected-errors.js';


test('expected connection failures do not become fatal error dumps', () => {
    assert.equal(shouldSuppressFatalOverlay(new TypeError('Failed to fetch')), true);
    assert.equal(
        shouldSuppressFatalOverlay(new DOMException('Timed out', 'AbortError')),
        true,
    );
});


test('unexpected client failures still reach the fatal error overlay', () => {
    assert.equal(
        shouldSuppressFatalOverlay(new Error('Malformed response payload')),
        false,
    );
});


test('input the server rejected becomes a polite warning, other failures do not', () => {
    assert.equal(
        rejectedInputWarning(new ServerInputRejectedError("Unclosed quote '\"' in search query")),
        "That could not be used: Unclosed quote '\"' in search query.",
    );
    // Unexpected failures stay fatal and loud.
    assert.equal(rejectedInputWarning(new HttpRequestError('API call failed: 500 Internal Server Error')), null);
    assert.equal(rejectedInputWarning(new Error('Malformed response payload')), null);
});


// The browser's note that a ResizeObserver's callback changed the layout again, so it holds the
// rest of its notifications for the next frame: not a failure in MetaList, and no error object
// comes with it. 0.28.1 listened from the login page on, caught it as the page laid itself out,
// and showed it as a fatal error on every load (the maintainer's dad, Windows, 2026-11-12).
test('the browser\'s ResizeObserver loop note is not a fatal error', () => {
    for (const message of [
        'ResizeObserver loop completed with undelivered notifications.',
        'ResizeObserver loop limit exceeded',
    ]) {
        assert.equal(isBrowserResizeObserverNote({ message, error: null }), true, message);
        assert.equal(isBrowserResizeObserverNote({ message, error: undefined }), true, message);
    }
});


test('a real error that mentions ResizeObserver still reaches the fatal error overlay', () => {
    const thrown = new Error('ResizeObserver loop completed with undelivered notifications.');
    assert.equal(isBrowserResizeObserverNote({ message: thrown.message, error: thrown }), false);
    assert.equal(isBrowserResizeObserverNote({ message: 'Script error.', error: null }), false);
});
