import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';

// Delete Folder (an experiment: virtual-folders-service.js): the folder comes off its notes,
// and, only when the box is ticked (unticked at first: the maintainer, 2026-11-01), the notes
// filed in it go too, each with the notes under it. Escape or Cancel changes nothing.

const SINGLE_NOTE = 1;

export class DeleteFolderModal extends BaseModal {
    constructor() {
        super('deleteFolderModal', 'delete-folder-modal');
        this._pendingResolve = null;
        this._form = null;
        this._result = null;

        ApplicationState.own(this, 'DeleteFolderModal', new.target === DeleteFolderModal);
    }

    getInitialModalState() {
        return {};
    }

    // Resolves to { deleteNotes } when confirmed, or null when nothing changes.
    // form: { path (the folder), noteCount (the notes filed in it, as the list counts them:
    // the notes under them go with them, uncounted) }.
    openFor({ path, noteCount }) {
        if (typeof path !== 'string' || path === '' || !Number.isInteger(noteCount) || noteCount < 0) {
            throw new Error('DeleteFolderModal.openFor requires a path and a note count');
        }
        if (this._pendingResolve !== null) {
            throw new Error('DeleteFolderModal already has a pending promise');
        }
        this._form = { path, noteCount };
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
            throw new Error('Delete folder modal has no element or form');
        }
        const { path, noteCount } = this._form;
        const notesWord = noteCount === SINGLE_NOTE ? 'note' : 'notes';
        const toggle = noteCount === 0 ? '' : `
                <label class="delete-folder-notes-toggle">
                    <input type="checkbox" id="delete-folder-notes">
                    <span>Also delete its ${noteCount} ${notesWord}</span>
                </label>`;
        modalElement.innerHTML = `
            <div class="modal-content alphabetize-root-notes-modal-content">
                <div class="prioritize-modal-header">
                    <p class="prioritize-modal-eyebrow">Virtual folders</p>
                    <h3>Delete ${escapeHtml(path)}?</h3>
                </div>
                <div class="alphabetize-root-notes-warning">
                    <p>The folder, and every folder in it, comes off its notes.</p>
                    ${toggle}
                </div>
                ${actionRowHtml({
                    alternative: null,
                    cancel: { id: 'delete-folder-cancel-btn', label: 'Cancel', disabled: false, attributes: [] },
                    main: {
                        id: 'delete-folder-submit-btn', label: 'Delete Folder', disabled: false, attributes: [],
                        isDestructive: true, isEnterAction: false, type: 'button',
                    },
                    rowClass: 'alphabetize-root-notes-actions',
                })}
            </div>
        `;
        this._wireForm();
    }

    _wireForm() {
        const submit = document.getElementById('delete-folder-submit-btn');
        const cancel = document.getElementById('delete-folder-cancel-btn');
        if (!(submit instanceof HTMLButtonElement) || !(cancel instanceof HTMLButtonElement)) {
            throw new Error('Delete folder modal is missing its buttons');
        }
        const box = document.getElementById('delete-folder-notes');
        if (box instanceof HTMLInputElement) {
            box.onchange = () => {
                submit.textContent = box.checked ? 'Delete Folder and Notes' : 'Delete Folder';
            };
        }
        submit.onclick = () => {
            this._result = { deleteNotes: box instanceof HTMLInputElement && box.checked };
            this.close();
        };
        cancel.onclick = () => this.close();
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
