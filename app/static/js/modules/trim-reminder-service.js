// The reminder to trim files no note uses (docs/ui/command-palette.md, `Trim Reminder`):
// a card in the notice stack, beside the backup reminder, once they add up to 10 MB. It
// only asks; its button opens Trim Unused Files' confirmation. It is checked when the app
// opens, when the tab comes back, when a dialog or the menu closes, and on the first click
// or key after a while, as the backup reminder is; it never polls.

import { ApplicationState } from './application-state.js';
import { appNoticeStack } from './app-notice-stack.js';
import { parseDecimalInteger } from './decimal-integer.js';
import { ModeContextInstance as ModeContext } from './mode-manager/mode-context.js';
import {
    TRIM_REMINDER_DEFAULT,
    TRIM_REMINDER_DISMISSED_BYTES_PREFERENCE,
    TRIM_REMINDER_OFF,
    TRIM_REMINDER_PREFERENCE,
    dismissedBytesAfter,
    isTrimReminderDue,
    trimReminderMessage,
} from './trim-reminder-schedule.js';

const NOTICE_ID = 'trim-reminder-notice';
const INTERACTION_CHECK_THROTTLE_MS = 30_000;
const NOTHING_DISMISSED_BYTES = 0;

class TrimReminderService {
    constructor() {
        this._started = false;
        this._preferences = null;
        this._fetchUnusedFiles = null;
        this._openTrim = null;
        // The unused bytes the card shows, for a dismiss to remember.
        this._shownBytes = null;
        this._lastInteractionCheckAt = 0;
        this._handleInteraction = this._handleInteraction.bind(this);
        this._handleVisibilityChange = this._handleVisibilityChange.bind(this);
        this._handleModeChange = this._handleModeChange.bind(this);
        ApplicationState.own(this, 'TrimReminderService', new.target === TrimReminderService);
    }

    async start({ preferences, fetchUnusedFiles, openTrim }) {
        if (this._started) {
            return;
        }
        if (!preferences || typeof preferences.getRaw !== 'function' || typeof preferences.setRaw !== 'function') {
            throw new Error('TrimReminder.start requires a preferences store');
        }
        if (typeof fetchUnusedFiles !== 'function' || typeof openTrim !== 'function') {
            throw new Error('TrimReminder.start requires fetchUnusedFiles and openTrim');
        }
        this._started = true;
        this._preferences = preferences;
        this._fetchUnusedFiles = fetchUnusedFiles;
        this._openTrim = openTrim;
        document.addEventListener('pointerdown', this._handleInteraction, { capture: true });
        document.addEventListener('keydown', this._handleInteraction, { capture: true });
        document.addEventListener('visibilitychange', this._handleVisibilityChange);
        ModeContext.addListener(this._handleModeChange);
        await this.check();
    }

    // The setting changed, or files were trimmed: show or hide the card at once.
    async preferencesChanged() {
        if (!this._started) {
            return;
        }
        await this.check();
    }

    async check() {
        if (!this._started || document.visibilityState !== 'visible') {
            return;
        }
        if (this._setting() === TRIM_REMINDER_OFF) {
            this._removeNotice();
            return;
        }
        // Wait for dialogs and the menu to close; closing one checks again.
        if (ModeContext.modalStack.length > 0) {
            return;
        }
        const unused = await this._fetchUnusedFiles();
        const unusedBytes = unused.size_bytes;
        const dismissedBytes = dismissedBytesAfter({ unusedBytes, dismissedBytes: this._dismissedBytes() });
        if (dismissedBytes !== this._dismissedBytes()) {
            await this._preferences.setRaw(TRIM_REMINDER_DISMISSED_BYTES_PREFERENCE, String(dismissedBytes));
        }
        if (!isTrimReminderDue({ setting: this._setting(), unusedBytes, dismissedBytes })) {
            this._removeNotice();
            return;
        }
        this._showNotice(unusedBytes);
    }

    _setting() {
        const stored = this._preferences.getRaw(TRIM_REMINDER_PREFERENCE);
        return stored === null ? TRIM_REMINDER_DEFAULT : stored;  // shockharness: ignore[DEF004] reason="an unset preference means the reminder's default, On"
    }

    _dismissedBytes() {
        const stored = this._preferences.getRaw(TRIM_REMINDER_DISMISSED_BYTES_PREFERENCE);
        if (stored === null) {
            return NOTHING_DISMISSED_BYTES;
        }
        const bytes = parseDecimalInteger(stored);
        if (!Number.isInteger(bytes) || bytes < 0) {
            throw new Error(`Trim reminder dismissed size is not a byte count: ${stored}`);
        }
        return bytes;
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
        void this.check();
    }

    _handleModeChange(property, value) {
        if (property !== 'modalStack' || value.length > 0) {
            return;
        }
        void this.check();
    }

    _showNotice(unusedBytes) {
        // Owned state rejects writing the value it already holds.
        if (this._shownBytes !== unusedBytes) {
            this._shownBytes = unusedBytes;
        }
        const existing = document.getElementById(NOTICE_ID);
        if (existing) {
            existing.querySelector('.backup-reminder-text').textContent = trimReminderMessage(unusedBytes);
            return;
        }
        const notice = document.createElement('aside');
        notice.id = NOTICE_ID;
        // Styled as the backup reminder, in the same corner.
        notice.className = 'app-update-notice backup-reminder-notice trim-reminder-notice reminder-surface-item';
        notice.setAttribute('role', 'status');
        const label = document.createElement('span');
        label.className = 'backup-reminder-text';
        label.textContent = trimReminderMessage(unusedBytes);
        const trim = document.createElement('button');
        trim.type = 'button';
        trim.textContent = 'Trim Unused Files…';
        trim.addEventListener('click', async () => { await this._openTrim(); });
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.textContent = '×';
        dismiss.setAttribute('aria-label', 'Hide the trim reminder until 10 MB more piles up');
        dismiss.title = 'Hide until 10 MB more piles up';
        dismiss.addEventListener('click', async () => { await this._dismiss(); });
        notice.append(label, trim, dismiss);
        appNoticeStack().append(notice);
    }

    async _dismiss() {
        const shownBytes = this._shownBytes;
        this._removeNotice();
        await this._preferences.setRaw(TRIM_REMINDER_DISMISSED_BYTES_PREFERENCE, String(shownBytes));
    }

    _removeNotice() {
        const notice = document.getElementById(NOTICE_ID);
        if (notice) {
            notice.remove();
        }
    }
}

export const TrimReminder = new TrimReminderService();
