// How often a view checks for changes made in other views (the maintainer, 2026-11-15): every
// second in a desktop browser, every 2 seconds on a phone. Tabs of one browser tell each other at
// once (views-in-this-browser.js), so they need no faster check.
import assert from 'node:assert/strict';
import test from 'node:test';

import { CONFIG } from '../../app/static/js/modules/config.js';
import { statusCheckIntervalMs } from '../../app/static/js/modules/status-check-interval.js';

const DESKTOP_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15';
const PHONE_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148';

function withAgent(userAgent, check) {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    Object.defineProperty(globalThis, 'navigator', { value: { userAgent }, configurable: true });
    check();
    Object.defineProperty(globalThis, 'navigator', original);
}

test('a desktop browser checks every second', () => {
    withAgent(DESKTOP_AGENT, () => assert.equal(statusCheckIntervalMs(), 1000));
    assert.equal(CONFIG.SYNC.POLL_INTERVAL_MS, 1000);
});

test('a phone checks every 2 seconds', () => {
    withAgent(PHONE_AGENT, () => assert.equal(statusCheckIntervalMs(), 2000));
});
