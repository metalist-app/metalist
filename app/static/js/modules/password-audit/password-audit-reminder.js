// The reminder to run the Password Audit (docs/ready-to-build/password-audit.md; the maintainer,
// 2026-11-12), made as the backup reminder is (backup-reminder-service.js): a card in the notice
// stack that takes no space and never takes focus, shown only when the vault holds a password.
// It is checked when the app opens, when the tab comes back, when a dialog or the menu closes, and
// on the first click or key after a while; it never polls. Audit Now opens the audit; × hides the
// card for a week; an audit that runs restarts the clock.

import { ApplicationState } from '../application-state.js';
import { appNoticeStack } from '../app-notice-stack.js';
import { ModeContextInstance as ModeContext } from '../mode-manager/mode-context.js';
import {
    PASSWORD_AUDIT_LAST_AUDITED_PREFERENCE,
    PASSWORD_AUDIT_OPEN_ISSUES_PREFERENCE,
    PASSWORD_AUDIT_REMINDER_DEFAULT,
    PASSWORD_AUDIT_REMINDER_HIDDEN_UNTIL_PREFERENCE,
    PASSWORD_AUDIT_REMINDER_HIDE_MS,
    PASSWORD_AUDIT_REMINDER_OFF,
    PASSWORD_AUDIT_REMINDER_PREFERENCE,
    isPasswordAuditReminderDue,
    passwordAuditReminderMessage,
} from './password-audit-reminder-schedule.js';

const NOTICE_ID = 'password-audit-reminder-notice';
const INTERACTION_CHECK_THROTTLE_MS = 30_000;

class PasswordAuditReminderService {
    constructor() {
        this._started = false;
        this._preferences = null;
        this._fetchPasswordCount = null;
        this._openAudit = null;
        // How many passwords the vault holds; null until fetched.
        this._passwordCount = null;
        this._lastInteractionCheckAt = 0;
        this._handleInteraction = this._handleInteraction.bind(this);
        this._handleVisibilityChange = this._handleVisibilityChange.bind(this);
        this._handleModeChange = this._handleModeChange.bind(this);
        ApplicationState.own(this, 'PasswordAuditReminderService', new.target === PasswordAuditReminderService);
    }

    async start({ preferences, fetchPasswordCount, openAudit }) {
        if (this._started) {
            return;
        }
        if (!preferences || typeof preferences.getRaw !== 'function' || typeof preferences.setRaw !== 'function') {
            throw new Error('PasswordAuditReminder.start requires a preferences store');
        }
        if (typeof fetchPasswordCount !== 'function' || typeof openAudit !== 'function') {
            throw new Error('PasswordAuditReminder.start requires fetchPasswordCount and openAudit');
        }
        this._started = true;
        this._preferences = preferences;
        this._fetchPasswordCount = fetchPasswordCount;
        this._openAudit = openAudit;
        document.addEventListener('pointerdown', this._handleInteraction, { capture: true });
        document.addEventListener('keydown', this._handleInteraction, { capture: true });
        document.addEventListener('visibilitychange', this._handleVisibilityChange);
        ModeContext.addListener(this._handleModeChange);
        await this.check();
    }

    // The reminder setting changed: show or hide the card at once.
    async preferencesChanged() {
        if (!this._started) {
            return;
        }
        await this.check();
    }

    // An audit ran: the clock restarts from now, and the card goes. openIssues is how many
    // passwords it left leaked, reused or weak: while any are, the card comes back sooner.
    async audited(openIssues) {
        if (!Number.isInteger(openIssues) || openIssues < 0) {
            throw new Error('PasswordAuditReminder.audited requires how many passwords still need attention');
        }
        if (!this._started) {
            return;
        }
        this._removeNotice();
        await this._preferences.setRaw(PASSWORD_AUDIT_LAST_AUDITED_PREFERENCE, new Date().toISOString());
        if (this._openIssues() !== openIssues) {
            await this._preferences.setRaw(PASSWORD_AUDIT_OPEN_ISSUES_PREFERENCE, String(openIssues));
        }
        this._forgetPasswordCount();
    }

    _openIssues() {
        const stored = this._preferences.getRaw(PASSWORD_AUDIT_OPEN_ISSUES_PREFERENCE);
        if (stored === null) {
            return 0;  // No audit has said otherwise.
        }
        return Number(stored);
    }

    async check() {
        if (!this._started || document.visibilityState !== 'visible') {
            return;
        }
        if (this._frequency() === PASSWORD_AUDIT_REMINDER_OFF) {
            this._removeNotice();
            return;
        }
        // Wait for dialogs and the menu to close; closing one checks again.
        if (ModeContext.modalStack.length > 0) {
            return;
        }
        if (this._passwordCount === null) {
            const count = await this._loadPasswordCount();
            // Another check may have loaded it meanwhile.
            if (this._passwordCount === null) {
                this._passwordCount = count;
            }
        }
        const now = new Date();
        const lastAuditedAt = this._storedMoment(PASSWORD_AUDIT_LAST_AUDITED_PREFERENCE);
        const openIssues = this._openIssues();
        const isDue = isPasswordAuditReminderDue({
            frequency: this._frequency(),
            passwordCount: this._passwordCount,
            lastAuditedAt,
            openIssues,
            hiddenUntil: this._storedMoment(PASSWORD_AUDIT_REMINDER_HIDDEN_UNTIL_PREFERENCE),
            now,
        });
        if (!isDue) {
            this._removeNotice();
            return;
        }
        this._showNotice(passwordAuditReminderMessage({ lastAuditedAt, openIssues, now }));
    }

    _frequency() {
        const stored = this._preferences.getRaw(PASSWORD_AUDIT_REMINDER_PREFERENCE);
        return stored === null ? PASSWORD_AUDIT_REMINDER_DEFAULT : stored;  // shockharness: ignore[DEF004] reason="an unset preference means the reminder's default, every 3 months"
    }

    _storedMoment(preference) {
        const stored = this._preferences.getRaw(preference);
        return stored === null ? null : parseMoment(stored);
    }

    async _loadPasswordCount() {
        const payload = await this._fetchPasswordCount();
        if (!payload || !Number.isInteger(payload.passwordCount) || payload.passwordCount < 0) {
            throw new Error('Password count response missing passwordCount');
        }
        return payload.passwordCount;
    }

    _handleInteraction() {
        const now = Date.now();
        if (now - this._lastInteractionCheckAt < INTERACTION_CHECK_THROTTLE_MS) {
            return;
        }
        this._lastInteractionCheckAt = now;
        void this.check();
    }

    _handleVisibilityChange() {
        if (document.visibilityState !== 'visible') {
            return;
        }
        // Passwords may have been added meanwhile, in this tab or another.
        this._forgetPasswordCount();
        void this.check();
    }

    _forgetPasswordCount() {
        if (this._passwordCount !== null) {
            this._passwordCount = null;
        }
    }

    _handleModeChange(property, value) {
        if (property !== 'modalStack' || value.length > 0) {
            return;
        }
        void this.check();
    }

    _showNotice(message) {
        const existing = document.getElementById(NOTICE_ID);
        if (existing) {
            existing.querySelector('.backup-reminder-text').textContent = message;
            return;
        }
        const notice = document.createElement('aside');
        notice.id = NOTICE_ID;
        notice.className = 'app-update-notice backup-reminder-notice reminder-surface-item';
        notice.setAttribute('role', 'status');
        const label = document.createElement('span');
        label.className = 'backup-reminder-text';
        label.textContent = message;
        const audit = document.createElement('button');
        audit.type = 'button';
        audit.textContent = 'Audit Now';
        audit.addEventListener('click', async () => { await this._openAudit(); });
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.textContent = '×';
        dismiss.setAttribute('aria-label', 'Hide the password audit reminder for a week');
        dismiss.title = 'Hide for a week';
        dismiss.addEventListener('click', async () => { await this._hideForAWeek(); });
        notice.append(label, audit, dismiss);
        appNoticeStack().append(notice);
    }

    async _hideForAWeek() {
        this._removeNotice();
        const hiddenUntil = new Date(Date.now() + PASSWORD_AUDIT_REMINDER_HIDE_MS);
        await this._preferences.setRaw(PASSWORD_AUDIT_REMINDER_HIDDEN_UNTIL_PREFERENCE, hiddenUntil.toISOString());
    }

    _removeNotice() {
        const notice = document.getElementById(NOTICE_ID);
        if (notice) {
            notice.remove();
        }
    }
}

function parseMoment(text) {
    if (typeof text !== 'string') {
        throw new Error('Password audit reminder time must be a string');
    }
    const moment = new Date(text);
    if (Number.isNaN(moment.getTime())) {
        throw new Error(`Password audit reminder time is not a date: ${text}`);
    }
    return moment;
}

export const PasswordAuditReminder = new PasswordAuditReminderService();
