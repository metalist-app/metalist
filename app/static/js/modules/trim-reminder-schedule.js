import { MIB, formatByteSize } from './byte-sizes.js';

// When the trim reminder shows (docs/ui/command-palette.md, `Trim Reminder`): files no
// note uses add up to 10 MB, and 10 MB more than when its card was last dismissed, so it
// never nags. Trimming stays the person's decision: the card only asks.

export const TRIM_REMINDER_PREFERENCE = 'pref.trim_reminder';
export const TRIM_REMINDER_DISMISSED_BYTES_PREFERENCE = 'pref.trim_reminder_dismissed_bytes';
export const TRIM_REMINDER_ON = 'on';
export const TRIM_REMINDER_OFF = 'off';
export const TRIM_REMINDER_DEFAULT = TRIM_REMINDER_ON;
// The card shows at this much, and again at this much more than when it was last dismissed.
const TRIM_REMINDER_STEP_MIB = 10;
export const TRIM_REMINDER_STEP_BYTES = TRIM_REMINDER_STEP_MIB * MIB;

export const TRIM_REMINDER_OPTIONS = Object.freeze([
    { value: TRIM_REMINDER_ON, label: 'On' },
    { value: TRIM_REMINDER_OFF, label: 'Off' },
]);

function requireByteCount(value, name) {
    if (!Number.isInteger(value) || value < 0) {
        throw new Error(`${name} must be a whole number of bytes`);
    }
}

export function isTrimReminderDue({ setting, unusedBytes, dismissedBytes }) {
    requireByteCount(unusedBytes, 'unusedBytes');
    requireByteCount(dismissedBytes, 'dismissedBytes');
    if (setting === TRIM_REMINDER_OFF) {
        return false;
    }
    if (setting !== TRIM_REMINDER_ON) {
        throw new Error(`Unknown trim reminder setting: ${setting}`);
    }
    return unusedBytes >= TRIM_REMINDER_STEP_BYTES && unusedBytes >= dismissedBytes + TRIM_REMINDER_STEP_BYTES;
}

// What a dismiss is measured from once unused files shrank below it (they were trimmed, or
// their notes came back): the smaller size, so another 10 MB from there shows the card.
export function dismissedBytesAfter({ unusedBytes, dismissedBytes }) {
    requireByteCount(unusedBytes, 'unusedBytes');
    requireByteCount(dismissedBytes, 'dismissedBytes');
    return Math.min(unusedBytes, dismissedBytes);
}

export function trimReminderMessage(unusedBytes) {
    return `${formatByteSize(unusedBytes)} of files aren't used by any note.`;
}

export function trimConfirmationText({ count, sizeBytes }) {
    const files = count === 1 ? 'file' : 'files';
    return `Delete ${count} unused ${files} (${formatByteSize(sizeBytes)})? This cannot be undone.`;
}
