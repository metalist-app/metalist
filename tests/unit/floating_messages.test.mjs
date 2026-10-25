import assert from 'node:assert/strict';
import test from 'node:test';

import { newsMilliseconds } from '../../app/static/js/modules/floating-messages.js';

// How long news stays (docs/ui/floating-messages.md): 4 s, longer for a long message,
// never more than 10 s.

const NEWS_MIN_MS = 4000;
const NEWS_MAX_MS = 10000;
const READING_MS_PER_CHARACTER = 60;
const LONG_MESSAGE_LENGTH = 100;
const VERY_LONG_MESSAGE_LENGTH = 400;

test('short news stays 4 s', () => {
    assert.equal(newsMilliseconds('Saved'), NEWS_MIN_MS);
});

test('long news stays as long as it takes to read', () => {
    assert.equal(newsMilliseconds('x'.repeat(LONG_MESSAGE_LENGTH)), LONG_MESSAGE_LENGTH * READING_MS_PER_CHARACTER);
});

test('very long news stays 10 s at most', () => {
    assert.equal(newsMilliseconds('x'.repeat(VERY_LONG_MESSAGE_LENGTH)), NEWS_MAX_MS);
});

test('news needs text', () => {
    assert.throws(() => newsMilliseconds(''), /requires message text/);
});
