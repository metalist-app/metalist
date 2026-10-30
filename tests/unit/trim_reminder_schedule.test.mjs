import assert from 'node:assert/strict';
import test from 'node:test';

import { MIB } from '../../app/static/js/modules/byte-sizes.js';
import {
    dismissedBytesAfter,
    isTrimReminderDue,
    trimConfirmationText,
    trimReminderMessage,
} from '../../app/static/js/modules/trim-reminder-schedule.js';

// docs/ui/command-palette.md, `Trim Reminder` (agreed 2026-10-27).
const due = (unusedMib, dismissedMib, setting) => isTrimReminderDue({
    setting, unusedBytes: unusedMib * MIB, dismissedBytes: dismissedMib * MIB,
});

test('the card shows once unused files reach 10 MB', () => {
    assert.deepEqual([due(9, 0, 'on'), due(10, 0, 'on')], [false, true]);
});

test('after a dismiss at 12 MB it waits for another 10 MB', () => {
    assert.deepEqual([due(15, 12, 'on'), due(22, 12, 'on')], [false, true]);
});

test('off shows no card at any size', () => {
    assert.equal(due(500, 0, 'off'), false);
});

test('a dismiss counts from the smaller size once unused files shrank', () => {
    assert.equal(dismissedBytesAfter({ unusedBytes: 1 * MIB, dismissedBytes: 12 * MIB }), 1 * MIB);
    assert.equal(dismissedBytesAfter({ unusedBytes: 15 * MIB, dismissedBytes: 12 * MIB }), 12 * MIB);
});

test('the card and the confirmation say what goes', () => {
    assert.equal(trimReminderMessage(12 * MIB), "12.0 MB of files aren't used by any note.");
    assert.equal(trimConfirmationText({ count: 4, sizeBytes: 12 * MIB }), 'Delete 4 unused files (12.0 MB)? This cannot be undone.');
    assert.equal(trimConfirmationText({ count: 1, sizeBytes: 2 * MIB }), 'Delete 1 unused file (2.0 MB)? This cannot be undone.');
});
