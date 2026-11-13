import assert from 'node:assert/strict';
import test from 'node:test';

import {
    PASSWORD_AUDIT_REMINDER_DEFAULT,
    PASSWORD_AUDIT_REMINDER_HIDE_MS,
    PASSWORD_AUDIT_REMINDER_OPTIONS,
    isPasswordAuditReminderDue,
    passwordAuditReminderMessage,
} from '../../app/static/js/modules/password-audit/password-audit-reminder-schedule.js';

// The Password Audit reminder (docs/ready-to-build/password-audit.md; the maintainer, 2026-11-12):
// every 3 months unless set otherwise; only when the vault holds a password; at once when no audit
// has ever run; × hides it for a week.
const NOW = new Date('2026-11-12T12:00:00Z');
const DAY_MS = 24 * 60 * 60 * 1000;
const daysAgo = (days) => new Date(NOW.getTime() - days * DAY_MS);
const due = (overrides) => isPasswordAuditReminderDue({
    frequency: PASSWORD_AUDIT_REMINDER_DEFAULT, passwordCount: 3, lastAuditedAt: null, openIssues: 0, hiddenUntil: null, now: NOW, ...overrides,
});

test('it is every 3 months unless set otherwise, with Off through Yearly to choose from', () => {
    assert.equal(PASSWORD_AUDIT_REMINDER_DEFAULT, 'every_3_months');
    assert.deepEqual(PASSWORD_AUDIT_REMINDER_OPTIONS.map((option) => option.label), ['Off', 'Monthly', 'Every 3 months', 'Every 6 months', 'Yearly']);
});

test('a vault with no password is never reminded', () => {
    assert.equal(due({ passwordCount: 0 }), false);
});

test('passwords never audited are due at once', () => {
    assert.equal(due({}), true);
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: null, openIssues: 0, now: NOW }), 'Time to check your passwords: they have never been audited.');
});

test('an audit restarts the clock for the chosen period', () => {
    assert.equal(due({ lastAuditedAt: daysAgo(89) }), false);
    assert.equal(due({ lastAuditedAt: daysAgo(90) }), true);
    assert.equal(due({ frequency: 'monthly', lastAuditedAt: daysAgo(30) }), true);
    assert.equal(due({ frequency: 'yearly', lastAuditedAt: daysAgo(364) }), false);
    assert.equal(due({ frequency: 'off' }), false);
});

test('x hides it for a week, then it comes back if still due', () => {
    assert.equal(PASSWORD_AUDIT_REMINDER_HIDE_MS, 7 * DAY_MS);
    assert.equal(due({ hiddenUntil: new Date(NOW.getTime() + DAY_MS) }), false);
    assert.equal(due({ hiddenUntil: new Date(NOW.getTime() - 1) }), true);
});

test('the card says days, then months', () => {
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: daysAgo(1), openIssues: 0, now: NOW }), 'Time to check your passwords: the last audit was 1 day ago.');
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: daysAgo(45), openIssues: 0, now: NOW }), 'Time to check your passwords: the last audit was 45 days ago.');
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: daysAgo(124), openIssues: 0, now: NOW }), 'Time to check your passwords: the last audit was 4 months ago.');
});

test('an unknown frequency is a bug, not a quiet no', () => {
    assert.throws(() => due({ frequency: 'weekly' }), /Unknown password audit reminder frequency: weekly/);
});

test('opening the audit counts, but while passwords still need attention it comes back after a month', () => {
    assert.equal(due({ lastAuditedAt: daysAgo(29), openIssues: 5 }), false);
    assert.equal(due({ lastAuditedAt: daysAgo(30), openIssues: 5 }), true);
    // With nothing left to fix, the chosen period again.
    assert.equal(due({ lastAuditedAt: daysAgo(30), openIssues: 0 }), false);
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: daysAgo(30), openIssues: 5, now: NOW }), 'Time to check your passwords: 5 still need attention.');
    assert.equal(passwordAuditReminderMessage({ lastAuditedAt: daysAgo(30), openIssues: 1, now: NOW }), 'Time to check your passwords: 1 still needs attention.');
});
