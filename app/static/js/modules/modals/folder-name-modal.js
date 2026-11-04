import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';

// A virtual folder's name (an experiment: virtual-folders-service.js), for New Folder and
// Rename Folder: the name is selected so typing replaces it. Enter does it, Escape or Cancel
// changes nothing, and a blank name can't be submitted. Spaces become dashes, as in a tag.

const SPACES_RE = /\s+/g;

export class FolderNameModal extends BaseModal {
    constructor() {
        super('folderNameModal', 'folder-name-modal');
        this._pendingResolve = null;
        this._form = null;
        this._result = null;

        ApplicationState.own(this, 'FolderNameModal', new.target === FolderNameModal);
    }

    getInitialModalState() {
        return {};
    }

    // Resolves to the name typed (spaces made dashes), or null when nothing changes.
    // form: { title, name (the current one, '' for a new folder), actionLabel }.
    openFor({ title, name, actionLabel }) {
        if (typeof title !== 'string' || typeof name !== 'string' || typeof actionLabel !== 'string') {
            throw new Error('FolderNameModal.openFor requires title, name and actionLabel');
        }
        if (this._pendingResolve !== null) {
            throw new Error('FolderNameModal already has a pending promise');
        }
        this._form = { title, name, actionLabel };
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
        if (!(modalElement instanceof HTMLElement) || this._form === null) {
            throw new Error('Folder name modal has no element or form');
        }
        const { title, name, actionLabel } = this._form;
        modalElement.innerHTML = `
            <div class="modal-content file-rename-modal-content">
                <h3>${escapeHtml(title)}</h3>
                <div class="form-group">
                    <label for="folder-name-input">Name</label>
                    <input id="folder-name-input" type="text" value="${escapeHtml(name)}" data-modal-initial-focus autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'folder-name-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'folder-name-submit-btn', label: actionLabel, disabled: name.trim() === '', attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        this._wireForm();
    }

    _elements() {
        const input = document.getElementById('folder-name-input');
        const submit = document.getElementById('folder-name-submit-btn');
        const cancel = document.getElementById('folder-name-cancel-btn');
        if (!(input instanceof HTMLInputElement) || !(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)) {
            throw new Error('Folder name modal is missing its field or buttons');
        }
        return { input, submit, cancel };
    }

    _wireForm() {
        const { input, submit, cancel } = this._elements();
        input.oninput = () => {
            const isBlank = input.value.trim() === '';
            if (submit.disabled !== isBlank) submit.disabled = isBlank;
        };
        submit.onclick = () => this._submit();
        cancel.onclick = () => this.close();
    }

    onOpen() {
        const { input } = this._elements();
        input.focus();
        input.select();
    }

    _submit() {
        const { input } = this._elements();
        const name = input.value.trim().replace(SPACES_RE, '-');
        if (name === '') {
            return;
        }
        if (name !== this._form.name) {
            this._result = name;
        }
        this.close();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._result;
        // The application state refuses a change to the value it holds already.
        if (resolve !== null) this._pendingResolve = null;
        if (this._form !== null) this._form = null;
        if (result !== null) this._result = null;
        if (resolve !== null) {
            resolve(result);
        }
    }
}
