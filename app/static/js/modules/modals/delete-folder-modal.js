import { ApplicationState } from '../application-state.js';
import { BaseModal } from './base-modal.js';
import { actionRowHtml } from './action-row.js';
import { escapeHtml } from '../html-escape.js';
import { filesAfterNotesText } from '../files-with-notes-text.js';

// Delete Folder (an experiment: virtual-folders-service.js): the folder comes off its notes,
// and, while the box is ticked, the notes filed in it go too, each with the notes under it,
// and the files only those notes use (ticked at first, and the files said with their size:
// the maintainer, 2026-11-18; it was unticked at first from 2026-11-01, and the files stayed
// until Trim Unused Files). Escape or Cancel changes nothing.

const SINGLE_NOTE = 1;
const DELETE_FOLDER_LABEL = 'Delete Folder';
const DELETE_BOTH_LABEL = 'Delete Folder and Notes';

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
    // the notes under them go with them, uncounted), fileCount and fileBytes (the files that
    // go with those notes) }.
    openFor({ path, noteCount, fileCount, fileBytes }) {
        const counts = [noteCount, fileCount, fileBytes];
        if (typeof path !== 'string' || path === '' || !counts.every((count) => Number.isInteger(count) && count >= 0)) {
            throw new Error('DeleteFolderModal.openFor requires a path and the counts of its notes and their files');
        }
        if (this._pendingResolve !== null) {
            throw new Error('DeleteFolderModal already has a pending promise');
        }
        this._form = { path, noteCount, fileCount, fileBytes };
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
        const { path, noteCount, fileCount, fileBytes } = this._form;
        const notesWord = noteCount === SINGLE_NOTE ? 'note' : 'notes';
        const files = filesAfterNotesText({ noteCount, fileCount, fileBytes });
        const hasNotes = noteCount > 0;
        const toggle = hasNotes ? `
                <label class="delete-folder-notes-toggle">
                    <input type="checkbox" id="delete-folder-notes" checked>
                    <span>Also delete its ${noteCount} ${notesWord}${escapeHtml(files)}</span>
                </label>` : '';
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
                        id: 'delete-folder-submit-btn', label: hasNotes ? DELETE_BOTH_LABEL : DELETE_FOLDER_LABEL, disabled: false, attributes: [],
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
                submit.textContent = box.checked ? DELETE_BOTH_LABEL : DELETE_FOLDER_LABEL;
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
