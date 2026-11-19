import assert from 'node:assert/strict';
import test from 'node:test';

import { auditSummaryText } from '../../app/static/js/modules/password-audit/audit-summary-text.js';

// Password Audit says what it counts as a password, the @password tag, and what to do in a vault
// with none (the maintainer, 2026-11-18).
const COUNTS = { leaked: 0, reused: 2, weak: 1, old: 0, replaced: 3 };

test('the line names the tag the audit reads, with each count', () => {
    assert.equal(auditSummaryText({ passwordCount: 12, summary: COUNTS, leakCheck: 'off' }),
        '12 passwords tagged @password: 0 leaked, 2 reused, 1 weak, 0 old');
    assert.equal(auditSummaryText({ passwordCount: 1, summary: { ...COUNTS, reused: 0 }, leakCheck: 'on' }),
        '1 password tagged @password: 0 leaked, 0 reused, 1 weak, 0 old');
});

test('a vault with no password says how to give the audit one', () => {
    assert.equal(auditSummaryText({ passwordCount: 0, summary: { leaked: 0, reused: 0, weak: 0, old: 0, replaced: 0 }, leakCheck: 'off' }),
        'No passwords: tag a note @password to audit it.');
});

test('while checking, and when the leak check cannot be reached', () => {
    assert.equal(auditSummaryText(null), 'Checking…');
    assert.equal(auditSummaryText({ passwordCount: 2, summary: COUNTS, leakCheck: 'unavailable' }),
        '2 passwords tagged @password: 0 leaked, 2 reused, 1 weak, 0 old (leak check unavailable)');
});
