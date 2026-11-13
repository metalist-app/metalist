import { DAYS_PER_WEEK, MS_PER_DAY } from '../time-units.js';

// When the Password Audit reminder is due (docs/ready-to-build/password-audit.md; the
// maintainer, 2026-11-12): the vault holds a password, the last audit is older than the chosen
// period (or there never was one: due at once), and × has not hidden it for now (a week). Opening
// the audit counts as one; while it left passwords leaked, reused or weak, the period is a month
// at most, and the card says how many.

export const PASSWORD_AUDIT_REMINDER_PREFERENCE = 'pref.password_audit_reminder';
export const PASSWORD_AUDIT_REMINDER_HIDDEN_UNTIL_PREFERENCE = 'pref.password_audit_reminder_hidden_until';
export const PASSWORD_AUDIT_LAST_AUDITED_PREFERENCE = 'pref.password_audit.last_audited_at';
export const PASSWORD_AUDIT_OPEN_ISSUES_PREFERENCE = 'pref.password_audit.open_issues';
export const PASSWORD_AUDIT_REMINDER_OFF = 'off';
// Until another is picked, every 3 months.
export const PASSWORD_AUDIT_REMINDER_DEFAULT = 'every_3_months';

const DAYS_IN_A_MONTH = 30;
const MONTHS_IN_A_QUARTER = 3;
const MONTHS_IN_HALF_A_YEAR = 6;
const DAYS_IN_A_YEAR = 365;
const PERIOD_DAYS_BY_FREQUENCY = Object.freeze({
    monthly: DAYS_IN_A_MONTH,
    every_3_months: MONTHS_IN_A_QUARTER * DAYS_IN_A_MONTH,
    every_6_months: MONTHS_IN_HALF_A_YEAR * DAYS_IN_A_MONTH,
    yearly: DAYS_IN_A_YEAR,
});
// While the last audit left passwords leaked, reused or weak, the card comes back after at most
// this long, saying how many (the maintainer, 2026-11-12: opening the audit counts, sooner if issues).
const DAYS_WITH_OPEN_ISSUES = DAYS_IN_A_MONTH;
// × hides the card for this long; running the audit restarts the clock instead.
export const PASSWORD_AUDIT_REMINDER_HIDE_MS = DAYS_PER_WEEK * MS_PER_DAY;
// From this many days on, the card says months rather than days.
const DAYS_BEFORE_SAYING_MONTHS = 60;

export const PASSWORD_AUDIT_REMINDER_OPTIONS = Object.freeze([
    { value: PASSWORD_AUDIT_REMINDER_OFF, label: 'Off' },
    { value: 'monthly', label: 'Monthly' },
    { value: 'every_3_months', label: 'Every 3 months' },
    { value: 'every_6_months', label: 'Every 6 months' },
    { value: 'yearly', label: 'Yearly' },
]);

function requireMoment(value, name) {
    if (!(value instanceof Date) || Number.isNaN(value.getTime())) {
        throw new Error(`${name} must be a valid Date`);
    }
}

function requireCount(value, name) {
    if (!Number.isInteger(value) || value < 0) {
        throw new Error(`${name} must be a count`);
    }
}

// `lastAuditedAt` and `hiddenUntil` are Dates, or null when there is none; `openIssues` is how many
// passwords the last audit left leaked, reused or weak.
export function isPasswordAuditReminderDue({ frequency, passwordCount, lastAuditedAt, openIssues, hiddenUntil, now }) {
    requireMoment(now, 'now');
    requireCount(passwordCount, 'passwordCount');
    requireCount(openIssues, 'openIssues');
    if (frequency === PASSWORD_AUDIT_REMINDER_OFF || passwordCount === 0) {
        return false;
    }
    if (!Object.hasOwn(PERIOD_DAYS_BY_FREQUENCY, frequency)) {
        throw new Error(`Unknown password audit reminder frequency: ${frequency}`);
    }
    if (hiddenUntil !== null) {
        requireMoment(hiddenUntil, 'hiddenUntil');
        if (now < hiddenUntil) {
            return false;
        }
    }
    if (lastAuditedAt === null) {
        return true;
    }
    requireMoment(lastAuditedAt, 'lastAuditedAt');
    let periodDays = PERIOD_DAYS_BY_FREQUENCY[frequency];
    if (openIssues > 0) {
        periodDays = Math.min(periodDays, DAYS_WITH_OPEN_ISSUES);
    }
    return now.getTime() - lastAuditedAt.getTime() >= periodDays * MS_PER_DAY;
}

export function passwordAuditReminderMessage({ lastAuditedAt, openIssues, now }) {
    requireMoment(now, 'now');
    requireCount(openIssues, 'openIssues');
    if (lastAuditedAt === null) {
        return 'Time to check your passwords: they have never been audited.';
    }
    if (openIssues > 0) {
        const verb = openIssues === 1 ? 'needs' : 'need';
        return `Time to check your passwords: ${openIssues} still ${verb} attention.`;
    }
    requireMoment(lastAuditedAt, 'lastAuditedAt');
    const days = Math.floor((now.getTime() - lastAuditedAt.getTime()) / MS_PER_DAY);
    if (days >= DAYS_BEFORE_SAYING_MONTHS) {
        return `Time to check your passwords: the last audit was ${Math.floor(days / DAYS_IN_A_MONTH)} months ago.`;
    }
    const unit = days === 1 ? 'day' : 'days';
    return `Time to check your passwords: the last audit was ${days} ${unit} ago.`;
}
