import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { CONFIG } from '../config.js';
import { FloatingMessages } from '../floating-messages.js';
import { isAnsweredStatus } from '../http-status.js';
import { rethrowUnexpectedError } from '../expected-errors.js';
import { setRestoringOpenVault } from '../restore-session-end.js';
import { setFieldMessage } from './field-message.js';
import { settleResult } from '../async-result.js';
import { showErrorDialogFor } from './error-dialog.js';
import { PASSWORD_MAX_LENGTH } from '../password-policy.js';
import { escapeHtml } from '../html-escape.js';

// Bringing in the old MetaList's notes (docs/ui/legacy-import.md; the maintainer, 2026-11-04):
// a new MetaList that finds them, in a namespace with no notes and no password, offers them
// once it opens. Protected notes ask for the old password, which then protects this MetaList
// too (a new one when it is too weak for the password rules). Bringing them in replaces the
// empty namespace and restarts the server, as restoring the open vault does; the page then
// reloads into the login screen. Declining is remembered: the palette's command stays.

export const LEGACY_IMPORT_DECLINED_PREFERENCE = 'pref.legacy_import_declined';
const DECLINED = 'true';
const PROGRESS_CARD_KEY = 'legacy-import-progress';
// As restoring the open vault (backup-restore-modal.js, error-handler.js, polling-service.js).
const RESTORE_TRANSITION_SUPPRESS_MS = 30_000;
const RESTORE_TRANSITION_UNTIL_KEY = 'metalist_restore_transition_until_ms';
const SERVER_REACHABILITY_POLL_INTERVAL_MS = 300;
const SERVER_REACHABILITY_REQUEST_TIMEOUT_MS = 1000;
const OLD_PASSWORD_FIELD_ID = 'legacy-import-old-password';
const NEW_PASSWORD_FIELD_ID = 'legacy-import-new-password';
const CONFIRM_PASSWORD_FIELD_ID = 'legacy-import-confirm-password';
const SUBMIT_BUTTON_ID = 'legacy-import-submit';
const CANCEL_BUTTON_ID = 'legacy-import-cancel';

function inputValue(fieldId) {
    const field = document.getElementById(fieldId);
    if (!(field instanceof HTMLInputElement)) {
        throw new Error(`Legacy import field missing: ${fieldId}`);
    }
    return field.value;
}

function passwordFieldHtml(fieldId, label, autocomplete) {
    return `
        <div class="form-group">
            <label for="${fieldId}">${label}</label>
            <input type="password" id="${fieldId}" autocomplete="${autocomplete}" maxlength="${PASSWORD_MAX_LENGTH}">
        </div>`;
}

export class LegacyImportModal extends BaseModal {
    // request(url, method, body): the palette's authenticated request; preferences: its store.
    constructor({ request, preferences }) {
        super('legacyImport', 'legacy-import-modal');
        if (typeof request !== 'function' || preferences === null || typeof preferences.setRaw !== 'function') {
            throw new Error('LegacyImportModal requires request and preferences');
        }
        this._request = request;
        this._preferences = preferences;
        this._encrypted = false;
        // The old password once it opened the notes, while a new one is asked for; '' otherwise.
        this._oldPassword = '';
        ApplicationState.own(this, 'LegacyImportModal', new.target === LegacyImportModal);
    }

    openFor({ encrypted }) {
        if (typeof encrypted !== 'boolean') {
            throw new Error('LegacyImportModal.openFor requires encrypted');
        }
        if (this._encrypted !== encrypted) this._encrypted = encrypted;
        return this.open();
    }

    getInitialModalState() {
        // asksNewPassword: the old password opens the notes but is too weak for the rules.
        return { encrypted: this._encrypted, asksNewPassword: false, ruleProblem: '', converting: false };
    }

    showModalElement() {
        let modalElement = document.getElementById(this.modalElementId);
        if (!modalElement) {
            modalElement = document.createElement('div');
            modalElement.id = this.modalElementId;
            modalElement.className = 'modal';
            modalElement.style.display = 'none';
            document.body.appendChild(modalElement);
        }
        this.renderModalContent();
        modalElement.style.display = 'block';
    }

    // Its first field is ready to type in: the render's focus came while it was still hidden.
    onOpen() {
        this._focusFirstField();
    }

    _focusFirstField() {
        const field = document.getElementById(this.modalElementId).querySelector('input');
        if (field instanceof HTMLInputElement) field.focus();
    }

    // While the notes come in the dialog stays open; it closes into the reload.
    canRequestClose() {
        return !this.getModalState().converting;
    }

    // Closing it without bringing them in is declining them: they are not offered again.
    onClose() {
        if (this._oldPassword !== '') this._oldPassword = '';
        if (this.getModalState().converting) return;
        if (this._preferences.getRaw(LEGACY_IMPORT_DECLINED_PREFERENCE) === DECLINED) return;
        void this._preferences.setRaw(LEGACY_IMPORT_DECLINED_PREFERENCE, DECLINED).catch((error) => {
            rethrowUnexpectedError(error);
            throw error;
        });
    }

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error('Legacy import modal element missing');
        }
        const state = this.getModalState();
        let fields = '';
        if (state.encrypted && !state.asksNewPassword) {
            fields = passwordFieldHtml(OLD_PASSWORD_FIELD_ID, 'Old password', 'current-password');
        } else if (state.asksNewPassword) {
            fields = `<p class="modal-muted">${escapeHtml(state.ruleProblem)}</p>`
                + passwordFieldHtml(NEW_PASSWORD_FIELD_ID, 'New password', 'new-password')
                + passwordFieldHtml(CONFIRM_PASSWORD_FIELD_ID, 'Confirm password', 'new-password');
        }
        modalElement.innerHTML = `
            <div class="modal-content legacy-import-modal-content">
                <h3>Notes from your old MetaList</h3>
                <p>Bring them in?</p>
                ${fields}
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: CANCEL_BUTTON_ID, label: 'Not Now', disabled: state.converting, attributes: [] },
                    main: {
                        id: SUBMIT_BUTTON_ID, label: 'Bring Them In', disabled: state.converting, attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: 'legacy-import-actions',
                })}
            </div>
        `;
        document.getElementById(CANCEL_BUTTON_ID).onclick = () => this.requestClose();
        document.getElementById(SUBMIT_BUTTON_ID).onclick = () => { void this._submit(); };
        this._focusFirstField();
    }

    async _submit() {
        const state = this.getModalState();
        if (state.converting) return;
        const result = await settleResult(async () => {
            if (!state.encrypted) {
                await this._convert(CONFIG.API.LEGACY_IMPORT.CONVERT, null);
                return;
            }
            if (state.asksNewPassword) {
                await this._convertWithNewPassword();
                return;
            }
            await this._convertWithOldPassword();
        });
        if (!result.ok) {
            this._endProgress();
            if (this.getModalState().converting) this.updateModalState({ converting: false });
            this.renderModalContent();
            await showErrorDialogFor(result.error, null);
        }
    }

    _check(legacyPassword, newPassword) {
        return this._request(CONFIG.API.LEGACY_IMPORT.CHECK_PASSWORD, 'POST', { legacy_password: legacyPassword, new_password: newPassword });
    }

    async _convertWithOldPassword() {
        const oldPassword = inputValue(OLD_PASSWORD_FIELD_ID);
        const field = document.getElementById(OLD_PASSWORD_FIELD_ID);
        if (oldPassword === '') {
            setFieldMessage(field, 'Type the old MetaList\u2019s password', 'error');
            return;
        }
        const check = await this._check(oldPassword, oldPassword);
        if (!check.opens) {
            setFieldMessage(field, 'Incorrect password', 'error');
            return;
        }
        setFieldMessage(field, '', 'error');
        if (check.new_password_problems.length > 0) {
            this._oldPassword = oldPassword;
            this.updateModalState({ asksNewPassword: true, ruleProblem: `The old password is too weak for this MetaList: ${check.new_password_problems.join(' ')}` });
            this.renderModalContent();
            return;
        }
        await this._convert(CONFIG.API.LEGACY_IMPORT.CONVERT_PROTECTED, { legacy_password: oldPassword, new_password: oldPassword });
    }

    async _convertWithNewPassword() {
        const newPassword = inputValue(NEW_PASSWORD_FIELD_ID);
        const newField = document.getElementById(NEW_PASSWORD_FIELD_ID);
        const confirmField = document.getElementById(CONFIRM_PASSWORD_FIELD_ID);
        const check = await this._check(this._oldPassword, newPassword);
        if (!check.opens) throw new Error('The old password no longer opens the old notes');
        setFieldMessage(newField, check.new_password_problems.join(' '), 'error');
        if (check.new_password_problems.length > 0) return;
        if (newPassword !== inputValue(CONFIRM_PASSWORD_FIELD_ID)) {
            setFieldMessage(confirmField, 'The passwords don\u2019t match', 'error');
            return;
        }
        setFieldMessage(confirmField, '', 'error');
        await this._convert(CONFIG.API.LEGACY_IMPORT.CONVERT_PROTECTED, { legacy_password: this._oldPassword, new_password: newPassword });
    }

    async _convert(url, body) {
        this.updateModalState({ converting: true });
        this.renderModalContent();
        FloatingMessages.showProgress(PROGRESS_CARD_KEY, 'Bringing in your old notes…');
        await this._request(url, 'POST', body);
        // The server restarts now and the session ends, as after restoring the open vault.
        sessionStorage.setItem(RESTORE_TRANSITION_UNTIL_KEY, String(Date.now() + RESTORE_TRANSITION_SUPPRESS_MS));
        setRestoringOpenVault(true);
        await this._reloadOnceServerAnswers();
    }

    _endProgress() {
        FloatingMessages.end(PROGRESS_CARD_KEY);
    }

    // The server answers, then restarts in its own process (auth.py, a moment later): the page
    // reloads once it has gone and come back, never from the process about to go.
    async _reloadOnceServerAnswers() {
        while (await this._serverAnswers()) {
            await this._pause();
        }
        while (!(await this._serverAnswers())) {
            await this._pause();
        }
        window.location.reload();
    }

    _pause() {
        return new Promise((resolve) => setTimeout(resolve, SERVER_REACHABILITY_POLL_INTERVAL_MS));
    }

    // Any reply, whatever its status, means the server is back; a refused or timed-out
    // request means it is not yet (backup-restore-modal.js).
    async _serverAnswers() {
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), SERVER_REACHABILITY_REQUEST_TIMEOUT_MS);
        const [outcome] = await Promise.allSettled([fetch('/maintenance', { method: 'GET', cache: 'no-store', signal: abortController.signal })]);
        clearTimeout(timeoutId);
        if (outcome.status === 'rejected') {
            rethrowUnexpectedError(outcome.reason);
            return false;
        }
        return isAnsweredStatus(outcome.value.status);
    }
}
