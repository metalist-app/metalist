import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';

// Rename File… (docs/ui/references.md, Renaming files): the name without its extension is
// edited, already selected so typing replaces it; the extension stays beside it, fixed.
// Enter renames, Escape or Cancel changes nothing, and a blank name can't be submitted.

// The extension starts at the last dot, unless that dot is the name's first or last
// character: ".bashrc" and "notes." have none (app/utils/file_names.py splits the same way).
export function splitFileExtension(name) {
    if (typeof name !== 'string') {
        throw new Error('splitFileExtension requires a name string');
    }
    const dot = name.lastIndexOf('.');
    if (dot <= 0 || dot === name.length - 1) {
        return { stem: name, extension: '' };
    }
    return { stem: name.slice(0, dot), extension: name.slice(dot) };
}

export class FileRenameModal extends BaseModal {
    constructor() {
        super('fileRenameModal', 'file-rename-modal');
        this._pendingResolve = null;
        this._file = null;
        this._result = null;

        ApplicationState.own(this, 'FileRenameModal', new.target === FileRenameModal);
    }

    getInitialModalState() {
        return {};
    }

    // Resolves to the whole new name (extension included), or null when nothing changes.
    openForFile({ fileId, name }) {
        if (typeof fileId !== 'string' || fileId === '') {
            throw new Error('FileRenameModal.openForFile requires fileId');
        }
        if (typeof name !== 'string' || name === '') {
            throw new Error('FileRenameModal.openForFile requires the current name');
        }
        if (this._pendingResolve !== null) {
            throw new Error('FileRenameModal already has a pending promise');
        }
        this._file = { fileId, name, ...splitFileExtension(name) };
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
            throw new Error('File rename modal element missing');
        }
        if (this._file === null) {
            throw new Error('File rename modal has no file');
        }
        const { stem, extension } = this._file;
        modalElement.innerHTML = `
            <div class="modal-content file-rename-modal-content">
                <h3>Rename File</h3>
                <div class="form-group">
                    <label for="file-rename-name">Name</label>
                    <div class="file-rename-name-row">
                        <input id="file-rename-name" type="text" value="${escapeHtml(stem)}" data-modal-initial-focus autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
                        ${extension === '' ? '' : `<span class="file-rename-extension">${escapeHtml(extension)}</span>`}
                    </div>
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'file-rename-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'file-rename-submit-btn', label: 'Rename', disabled: stem.trim() === '', attributes: [],
                        isDestructive: false, isEnterAction: true, type: 'button',
                    },
                    rowClass: '',
                })}
            </div>
        `;
        this._wireForm();
    }

    _elements() {
        const input = document.getElementById('file-rename-name');
        const submit = document.getElementById('file-rename-submit-btn');
        const cancel = document.getElementById('file-rename-cancel-btn');
        if (!(input instanceof HTMLInputElement) || !(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)) {
            throw new Error('File rename modal is missing its field or buttons');
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
        const stem = input.value.trim();
        if (stem === '') {
            return;
        }
        const name = `${stem}${this._file.extension}`;
        if (name !== this._file.name) {
            this._result = name;
        }
        this.close();
    }

    onClose() {
        const resolve = this._pendingResolve;
        const result = this._result;
        // The application state refuses a change to the value it holds already.
        if (resolve !== null) this._pendingResolve = null;
        if (this._file !== null) this._file = null;
        if (result !== null) this._result = null;
        if (resolve !== null) {
            resolve(result);
        }
    }
}
