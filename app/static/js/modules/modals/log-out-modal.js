import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';

// Log Out (multi-view editing, 2026-11-14; docs/ready-to-build/multi-view-editing.md §9): this
// browser or device, every tab of it; ticked, every device, which in a vault with a password
// locks it. Unticked at first. Escape or Cancel changes nothing. Replaces a separate Lock Vault.

export class LogOutModal extends BaseModal {
    constructor() {
        super('logOutModal', 'log-out-modal');
        this._pendingResolve = null;
        this._result = null;

        ApplicationState.own(this, 'LogOutModal', new.target === LogOutModal);
    }

    getInitialModalState() {
        return {};
    }

    // Resolves to { everyDevice } when confirmed, or null when nothing changes.
    ask() {
        if (this._pendingResolve !== null) {
            throw new Error('LogOutModal already has a pending promise');
        }
        this.open();
        return new Promise((resolve) => {
            this._pendingResolve = resolve;
        });
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

    renderModalContent() {
        const modalElement = document.getElementById(this.modalElementId);
        if (!(modalElement instanceof HTMLElement)) {
            throw new Error('Log out modal has no element');
        }
        modalElement.innerHTML = `
            <div class="modal-content alphabetize-root-notes-modal-content">
                <div class="prioritize-modal-header">
                    <h3>Log Out</h3>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="log-out-every-device">
                        Sign out every device
                    </label>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'log-out-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'log-out-submit-btn', label: 'Log Out', disabled: false, attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: 'alphabetize-root-notes-actions',
                })}
            </div>
        `;
        this._wireForm();
    }

    _wireForm() {
        const submit = document.getElementById('log-out-submit-btn');
        const cancel = document.getElementById('log-out-cancel-btn');
        const box = document.getElementById('log-out-every-device');
        if (!(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)
            || !(box instanceof HTMLInputElement)) {
            throw new Error('Log out modal is missing its buttons or its box');
        }
        submit.onclick = () => {
            this._result = { everyDevice: box.checked };
            this.close();
        };
        cancel.onclick = () => this.close();
        submit.focus();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._result;
        // The application state refuses a change to the value it holds already.
        if (resolve !== null) this._pendingResolve = null;
        if (result !== null) this._result = null;
        if (resolve !== null) {
            resolve(result);
        }
    }
}
